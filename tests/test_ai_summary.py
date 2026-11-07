import json

import pytest

from app.extensions import db
from app.models import Conversation, Message, TaskOutbox
from app.services.conversation_service import ConversationOperations
from app.services.customer_service import CustomerOperations
from app.services.exceptions import ExternalServiceError
from app.services.groq_service import GroqGateway
from app.services.outbox import DispatchOutboxBestEffortService
from app.tasks.ai_tasks import generate_summary


@pytest.fixture
def summary_conversation(company_factory, monkeypatch):
    company = company_factory()
    customer = CustomerOperations.upsert_from_whatsapp(company.id, phone="5511999991234")
    conversation = Conversation(company_id=company.id, customer_id=customer.id)
    db.session.add(conversation)
    db.session.commit()
    monkeypatch.setattr(DispatchOutboxBestEffortService, "execute", lambda self, entry_id: False)
    return conversation


def add_message(conversation, content, **fields):
    message = Message(
        company_id=conversation.company_id,
        conversation_id=conversation.id,
        direction=fields.pop("direction", "INBOUND"),
        sender_type=fields.pop("sender_type", "CUSTOMER"),
        content=content,
        **fields,
    )
    db.session.add(message)
    db.session.flush()
    return message


def groq_response(summary):
    return {"choices": [{"message": {"content": summary}}]}


def test_summary_cursor_matches_serialized_prefix(summary_conversation, monkeypatch):
    conversation = summary_conversation
    escaped_text = '"' * 9000
    add_message(conversation, escaped_text)
    filtered = add_message(conversation, "")
    remaining = add_message(conversation, escaped_text)
    db.session.commit()
    calls = []

    def complete(self, messages, **kwargs):
        payload = messages[1]["content"]
        assert len(payload) <= 30_000
        calls.append(json.loads(payload))
        return groq_response(f"Resumo {len(calls)}")

    monkeypatch.setattr(GroqGateway, "chat_completion", complete)

    assert generate_summary.run(conversation.id)["cursor"] == filtered.id
    continuation = TaskOutbox.query.one()
    assert continuation.task_name == "generate_summary"
    assert continuation.payload_json == {"conversation_id": conversation.id}
    assert generate_summary.run(conversation.id)["cursor"] == remaining.id
    assert calls == [
        {"previous_summary": "", "new_messages": [{"role": "user", "content": escaped_text}]},
        {
            "previous_summary": "Resumo 1",
            "new_messages": [{"role": "user", "content": escaped_text}],
        },
    ]


def test_oversized_message_requires_every_part_before_progress(summary_conversation, monkeypatch):
    conversation = summary_conversation
    content = '"' * 16000
    oversized = add_message(conversation, content)
    db.session.commit()
    parts = []

    def complete(self, messages, **kwargs):
        payload = messages[1]["content"]
        assert len(payload) <= 30_000
        parts.append(json.loads(payload)["new_messages"][0]["content"])
        return groq_response("Resumo parcial" if len(parts) == 1 else " ")

    monkeypatch.setattr(GroqGateway, "chat_completion", complete)
    with pytest.raises(ExternalServiceError, match="empty summary"):
        generate_summary.run(conversation.id)
    assert not (conversation.memory_json or {}).get("summarized_through_message_id")
    assert not conversation.summary

    def retry_complete(self, messages, **kwargs):
        parts.append(json.loads(messages[1]["content"])["new_messages"][0]["content"])
        return groq_response("Resumo completo")

    parts.clear()
    monkeypatch.setattr(GroqGateway, "chat_completion", retry_complete)
    assert generate_summary.run(conversation.id)["cursor"] == oversized.id
    assert "".join(parts) == content


def test_summary_splits_large_escaped_message_without_blocking_cursor(
    summary_conversation, monkeypatch
):
    conversation = summary_conversation
    content = "\t" * 30_000 + "\x00" * 25_000
    message = add_message(conversation, content)
    db.session.commit()
    parts = []

    def complete(self, messages, **kwargs):
        payload = messages[1]["content"]
        assert len(payload) <= 30_000
        parts.append(json.loads(payload)["new_messages"][0]["content"])
        return groq_response("Resumo")

    monkeypatch.setattr(GroqGateway, "chat_completion", complete)
    assert generate_summary.run(conversation.id)["cursor"] == message.id
    assert "".join(parts) == content


def test_summary_does_not_advance_past_pending_outbound(summary_conversation, monkeypatch):
    conversation = summary_conversation
    first = add_message(conversation, "Pergunta")
    pending = add_message(
        conversation, "Resposta", direction="OUTBOUND", sender_type="AI", status="QUEUED"
    )
    last = add_message(conversation, "Obrigado")
    db.session.commit()
    calls = []

    def complete(self, messages, **kwargs):
        calls.append(json.loads(messages[1]["content"])["new_messages"])
        return groq_response("Resumo")

    monkeypatch.setattr(GroqGateway, "chat_completion", complete)
    assert generate_summary.run(conversation.id)["cursor"] == first.id
    pending.status = "SENT"
    db.session.commit()
    assert generate_summary.run(conversation.id)["cursor"] == last.id
    assert calls == [
        [{"role": "user", "content": "Pergunta"}],
        [{"role": "assistant", "content": "Resposta"}, {"role": "user", "content": "Obrigado"}],
    ]


def test_pending_at_cursor_retries_without_calling_groq(summary_conversation, monkeypatch):
    conversation = summary_conversation
    assert generate_summary.run(conversation.id)["status"] == "current"
    add_message(conversation, "Resposta", direction="OUTBOUND", sender_type="AI", status="SENDING")
    db.session.commit()

    def retry(**kwargs):
        assert kwargs == {"countdown": 120, "max_retries": 30}
        return RuntimeError("retry pending")

    monkeypatch.setattr(generate_summary, "retry", retry)
    with pytest.raises(RuntimeError, match="retry pending"):
        generate_summary.run(conversation.id)
    assert TaskOutbox.query.count() == 0
    assert not (conversation.memory_json or {}).get("summarized_through_message_id")


def test_summary_retries_if_response_is_truncated(summary_conversation, monkeypatch):
    conversation = summary_conversation
    add_message(conversation, "Pergunta")
    db.session.commit()

    def complete(self, messages, **kwargs):
        return {"choices": [{"message": {"content": "Resumo parcial"}, "finish_reason": "length"}]}

    monkeypatch.setattr(GroqGateway, "chat_completion", complete)
    with pytest.raises(ExternalServiceError, match="truncated summary"):
        generate_summary.run(conversation.id)
    assert not (conversation.memory_json or {}).get("summarized_through_message_id")


def test_summary_discards_result_based_on_stale_cursor(summary_conversation, monkeypatch):
    conversation = summary_conversation
    first = add_message(conversation, "Primeira")
    last = add_message(conversation, "Última")
    db.session.commit()

    def complete(self, messages, **kwargs):
        ConversationOperations.set_summary(
            conversation.company_id,
            conversation.id,
            summary="Resumo concorrente",
            summarized_through_message_id=first.id,
        )
        return groq_response("Resumo desatualizado")

    monkeypatch.setattr(GroqGateway, "chat_completion", complete)
    assert generate_summary.run(conversation.id)["status"] == "stale"
    assert conversation.summary == "Resumo concorrente"
    assert conversation.memory_json["summarized_through_message_id"] == first.id
    assert first.id < last.id
