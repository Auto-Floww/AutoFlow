"""Transições persistidas pelas tarefas Celery."""

from datetime import timedelta

import pytest

from app.extensions import db
from app.models import Conversation, Customer, Message
from app.models.base import utcnow
from app.services.exceptions import ValidationError
from app.services.whatsapp_service import WhatsAppService
from app.tasks.ai_tasks import send_whatsapp_message


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
