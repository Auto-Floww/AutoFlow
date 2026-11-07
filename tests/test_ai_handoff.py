"""Handoff da IA com pausa, notificação e confirmação transacional."""

import pytest

from app.extensions import db
from app.models import Customer, Message, Notification, TaskOutbox
from app.services.ai_tools import build_default_registry
from app.services.conversation_service import HANDOFF_CONFIRMATION, ConversationOperations
from app.services.groq_service import GroqService
from app.services.outbox import EnqueueOutboxTaskService
from app.services.tool_registry import ToolContext
from app.services.whatsapp_service import WhatsAppService
from app.tasks.ai_tasks import process_message, send_whatsapp_message


@pytest.fixture
def chat(app, tenant_user):
    app.config["OUTBOX_IMMEDIATE_DISPATCH"] = False
    customer = Customer(
        company_id=tenant_user.company_id,
        name="Cliente",
        phone="+55 11 97777-4444",
        phone_normalized="5511977774444",
    )
    db.session.add(customer)
    db.session.flush()
    conversation, _ = ConversationOperations.get_or_create(
        tenant_user.company_id, customer_id=customer.id
    )
    inbound, _ = ConversationOperations.record_inbound(
        tenant_user.company_id,
        conversation_id=conversation.id,
        content="Quero falar com um atendente.",
        external_message_id="handoff-inbound",
    )
    return conversation, inbound


def _handoff(conversation):
    return build_default_registry().execute(
        "transfer_to_human",
        {"reason": "Cliente pediu um atendente"},
        ToolContext(conversation.company_id, conversation.id),
    )


def _confirmation():
    return Message.query.filter_by(direction="OUTBOUND", content=HANDOFF_CONFIRMATION).one()


def test_worker_handoff_is_terminal_and_retry_safe(chat, monkeypatch):
    conversation, inbound = chat
    completions = []

    def groq(gateway, messages, **kwargs):
        completions.append(messages)
        assert len(completions) == 1
        return {
            "choices": [{"message": {
                "role": "assistant",
                "tool_calls": [
                    {"id": "handoff", "function": {"name": "transfer_to_human"}},
                    {"id": "next", "function": {"name": "search_products"}},
                ],
            }}],
        }

    registry = build_default_registry()
    execute = registry.execute
    calls = []

    def record_call(name, *args):
        calls.append(name)
        return execute(name, *args)

    monkeypatch.setattr(registry, "execute", record_call)
    monkeypatch.setattr("app.services.groq_service.build_default_registry", lambda: registry)
    monkeypatch.setattr(GroqService, "chat_completion", groq)
    answer = GroqService.answer_conversation

    def answer_then_resume(gateway, conversation, **kwargs):
        result = answer(gateway, conversation, **kwargs)
        assert conversation.human_requested and conversation.ai_status == "PAUSED"
        assert "processing_message_id" not in conversation.memory_json
        ConversationOperations.return_to_ai(conversation.company_id, conversation.id)
        return result

    monkeypatch.setattr(GroqService, "answer_conversation", answer_then_resume)
    assert process_message.run(inbound.id)["status"] == "transferred"
    assert calls == ["transfer_to_human"]
    assert conversation.ai_status == "ACTIVE"
    assert inbound.processing_status == "PROCESSED"
    confirmation = _confirmation()
    assert confirmation.reply_to_id == inbound.id
    assert Notification.query.filter_by(notification_type="HUMAN_REQUESTED").count() == 1
    outbox = TaskOutbox.query.filter_by(task_name="send_whatsapp_message").one()
    assert outbox.payload_json == {"message_id": confirmation.id}

    assert process_message.run(inbound.id)["status"] == "processed"
    assert Message.query.filter_by(direction="OUTBOUND").count() == 1


def test_only_current_confirmation_bypasses_pause_after_agent_claim(
    chat, tenant_user, monkeypatch
):
    conversation, _ = chat
    generic = ConversationOperations.record_outbound(
        conversation.company_id, conversation_id=conversation.id, content="Resposta comum."
    )
    assert _handoff(conversation)["ok"]
    assert _handoff(conversation)["ok"]
    confirmation = _confirmation()
    ConversationOperations.claim(conversation.company_id, conversation.id, user_id=tenant_user.id)
    sent = []

    def fake_send(service, company_id, **kwargs):
        sent.append(kwargs["text"])
        return {"key": {"id": "confirmation-provider-id"}}

    monkeypatch.setattr(WhatsAppService, "send_text", fake_send)
    assert send_whatsapp_message.run(generic.id)["status"] == "ai_paused"
    assert send_whatsapp_message.run(confirmation.id)["status"] == "sent"
    assert send_whatsapp_message.run(confirmation.id)["status"] == "sent"
    assert sent == [HANDOFF_CONFIRMATION]
    assert conversation.assigned_user_id == tenant_user.id
    assert not conversation.human_requested
    assert Notification.query.filter_by(notification_type="HUMAN_REQUESTED").count() == 1
    assert TaskOutbox.query.filter_by(task_name="send_whatsapp_message").count() == 1


def test_resumed_ai_invalidates_queued_confirmation(chat, tenant_user, monkeypatch):
    conversation, _ = chat
    assert _handoff(conversation)["ok"]
    confirmation = _confirmation()
    ConversationOperations.return_to_ai(conversation.company_id, conversation.id)
    ConversationOperations.claim(conversation.company_id, conversation.id, user_id=tenant_user.id)

    def unexpected_send(*args, **kwargs):
        pytest.fail("A superseded confirmation reached the WhatsApp gateway")

    monkeypatch.setattr(WhatsAppService, "send_text", unexpected_send)
    assert send_whatsapp_message.run(confirmation.id)["status"] == "handoff_superseded"


def test_agent_claim_during_groq_stays_in_control(chat, tenant_user, monkeypatch):
    conversation, inbound = chat

    def groq(*args, **kwargs):
        assert conversation.ai_status == "ACTIVE"
        ConversationOperations.claim(
            conversation.company_id, conversation.id, user_id=tenant_user.id
        )
        return {
            "choices": [{"message": {
                "role": "assistant",
                "tool_calls": [{"id": "handoff", "function": {"name": "transfer_to_human"}}],
            }}],
        }

    monkeypatch.setattr(GroqService, "chat_completion", groq)
    assert process_message.run(inbound.id)["status"] == "ai_paused"
    assert inbound.processing_status == "SKIPPED"
    assert conversation.assigned_user_id == tenant_user.id
    assert not conversation.human_requested
    assert not Message.query.filter_by(direction="OUTBOUND").count()
    assert not TaskOutbox.query.count()


def test_outbox_failure_rolls_back_entire_handoff(chat, monkeypatch):
    conversation, _ = chat

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(EnqueueOutboxTaskService, "execute", fail_enqueue)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        _handoff(conversation)
    assert conversation.ai_status == "ACTIVE"
    assert not conversation.human_requested
    assert not Notification.query.count()
    assert not Message.query.filter_by(direction="OUTBOUND").count()
    assert not TaskOutbox.query.count()
