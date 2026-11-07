"""Transições persistidas pelas tarefas Celery."""

from datetime import timedelta

import pytest

from app.extensions import db
from app.models import AISettings, Conversation, Customer, Message
from app.models.base import utcnow
from app.services.exceptions import ValidationError
from app.services.groq_service import GroqService
from app.services.whatsapp_service import WhatsAppService
from app.tasks.ai_tasks import process_message, send_whatsapp_message


def _outbound_message(company_id: int) -> Message:
    customer = Customer(
        company_id=company_id,
        name="Cliente da task",
        phone="+55 11 97777-4444",
        phone_normalized="5511977774444",
    )
    db.session.add(customer)
    db.session.flush()
    conversation = Conversation(
        company_id=company_id,
        customer_id=customer.id,
        channel="WHATSAPP",
        ai_status="ACTIVE",
    )
    db.session.add(conversation)
    db.session.flush()
    message = Message(
        company_id=company_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        direction="OUTBOUND",
        sender_type="AGENT",
        content="Mensagem pronta para envio.",
        status="QUEUED",
        processing_status="SKIPPED",
    )
    db.session.add(message)
    db.session.commit()
    return message


def test_process_message_only_completes_messages_in_groq_history(tenant_user, monkeypatch):
    outbound = _outbound_message(tenant_user.company_id)
    db.session.add(AISettings(company_id=tenant_user.company_id, history_limit=2))
    inbounds = [
        Message(
            company_id=outbound.company_id,
            conversation_id=outbound.conversation_id,
            customer_id=outbound.customer_id,
            direction="INBOUND",
            sender_type="CUSTOMER",
            content=f"Pergunta {number}",
        )
        for number in range(1, 4)
    ]
    db.session.add_all(inbounds)
    db.session.commit()
    requests = []

    def answer(service, messages, **kwargs):
        requests.append([item["content"] for item in messages if item["role"] == "user"])
        return "Resposta", {}

    monkeypatch.setattr(GroqService, "run_tool_loop", answer)
    monkeypatch.setattr(
        WhatsAppService, "send_text", lambda *args, **kwargs: {"key": {"id": "test-id"}}
    )
    first, second, third = inbounds

    result = process_message.run(first.id)
    assert result["batched_message_ids"] == [first.id]
    assert second.processing_status == third.processing_status == "PENDING"

    result = process_message.run(second.id)
    assert set(result["batched_message_ids"]) == {second.id, third.id}
    assert process_message.run(third.id)["status"] == "processed"
    assert requests == [["Pergunta 1"], ["Pergunta 2", "Pergunta 3"]]


def test_send_whatsapp_transitions_sending_to_sent(
    tenant_user, monkeypatch
):
    message = _outbound_message(tenant_user.company_id)
    observed = []

    def fake_send_text(service, company_id, **kwargs):
        current = db.session.get(Message, message.id)
        observed.append(
            {
                "status": current.status,
                "lease": current.ai_metadata_json.get("whatsapp_send_started_at"),
                "company_id": company_id,
                "to": kwargs["to"],
            }
        )
        return {"messages": [{"id": "wamid.outbound-success"}]}

    monkeypatch.setattr(WhatsAppService, "send_text", fake_send_text)

    result = send_whatsapp_message.run(message.id)

    db.session.expire_all()
    persisted = db.session.get(Message, message.id)
    assert observed == [
        {
            "status": "SENDING",
            "lease": observed[0]["lease"],
            "company_id": tenant_user.company_id,
            "to": "5511977774444",
        }
    ]
    assert observed[0]["lease"]
    assert result == {
        "status": "sent",
        "message_id": message.id,
        "external_message_id": "wamid.outbound-success",
    }
    assert persisted.status == "SENT"
    assert persisted.external_message_id == "wamid.outbound-success"
    assert persisted.sent_at is not None
    assert "whatsapp_send_started_at" not in persisted.ai_metadata_json


def test_send_whatsapp_accepts_evolution_v2_key_id(tenant_user, monkeypatch):
    message = _outbound_message(tenant_user.company_id)

    monkeypatch.setattr(
        WhatsAppService,
        "send_text",
        lambda *args, **kwargs: {"key": {"id": "evolution-v2-id"}},
    )

    result = send_whatsapp_message.run(message.id)

    db.session.expire_all()
    persisted = db.session.get(Message, message.id)
    assert result["external_message_id"] == "evolution-v2-id"
    assert persisted.status == "SENT"
    assert persisted.external_message_id == "evolution-v2-id"


def test_old_evolution_parser_failure_is_not_resent(tenant_user, monkeypatch):
    message = _outbound_message(tenant_user.company_id)
    message.error_message = "WhatsApp returned no message identifier"
    db.session.commit()
    send_calls = []
    monkeypatch.setattr(
        WhatsAppService,
        "send_text",
        lambda *args, **kwargs: send_calls.append((args, kwargs)),
    )

    result = send_whatsapp_message.run(message.id)

    db.session.expire_all()
    persisted = db.session.get(Message, message.id)
    assert result == {"status": "delivery_unknown", "message_id": message.id}
    assert send_calls == []
    assert persisted.status == "FAILED"
    assert "verify WhatsApp" in persisted.error_message

    # A broker redelivery remains a no-op after the status transition.
    assert send_whatsapp_message.run(message.id) == {
        "status": "delivery_unknown",
        "message_id": message.id,
    }
    assert send_calls == []


def test_send_whatsapp_domain_error_transitions_sending_to_failed(
    tenant_user, monkeypatch
):
    message = _outbound_message(tenant_user.company_id)
    observed_statuses = []

    def rejected_send(service, company_id, **kwargs):
        current = db.session.get(Message, message.id)
        observed_statuses.append(current.status)
        raise ValidationError("Integracao WhatsApp indisponivel")

    monkeypatch.setattr(WhatsAppService, "send_text", rejected_send)

    with pytest.raises(ValidationError, match="indisponivel"):
        send_whatsapp_message.run(message.id)

    db.session.expire_all()
    persisted = db.session.get(Message, message.id)
    assert observed_statuses == ["SENDING"]
    assert persisted.status == "FAILED"
    assert persisted.error_message == "Integracao WhatsApp indisponivel"
    assert "whatsapp_send_started_at" not in persisted.ai_metadata_json


def test_send_whatsapp_expired_sending_lease_requires_reconciliation(
    tenant_user, monkeypatch
):
    message = _outbound_message(tenant_user.company_id)
    message.status = "SENDING"
    message.ai_metadata_json = {
        "whatsapp_send_started_at": (utcnow() - timedelta(minutes=2)).isoformat()
    }
    db.session.commit()
    meta_calls = []

    monkeypatch.setattr(
        WhatsAppService,
        "send_text",
        lambda *args, **kwargs: meta_calls.append((args, kwargs)),
    )

    result = send_whatsapp_message.run(message.id)

    db.session.expire_all()
    persisted = db.session.get(Message, message.id)
    assert result == {"status": "delivery_unknown", "message_id": message.id}
    assert meta_calls == []
    assert persisted.status == "FAILED"
    assert persisted.error_message == "delivery outcome unknown"
    assert "whatsapp_send_started_at" not in persisted.ai_metadata_json
