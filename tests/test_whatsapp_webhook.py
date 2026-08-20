"""Verificação, assinatura, idempotência e enqueue do webhook Meta."""

import hashlib
import hmac
import json

from app.extensions import db
from app.models import (
    Conversation,
    Customer,
    Message,
    TaskOutbox,
    WhatsAppIntegration,
)


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _message_payload(phone_number_id: str, message_id: str = "wamid.001") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [
                                {
                                    "wa_id": "5511999993333",
                                    "profile": {"name": "Cliente Meta"},
                                }
                            ],
                            "messages": [
                                {
                                    "from": "5511999993333",
                                    "id": message_id,
                                    "timestamp": "1893459600",
                                    "type": "text",
                                    "text": {"body": "Tem camiseta preta tamanho M?"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def test_webhook_verification_challenge(client, app):
    app.config["WHATSAPP_VERIFY_TOKEN"] = "verify-local"

    accepted = client.get(
        "/webhooks/whatsapp",
        query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-local",
            "hub.challenge": "123456",
        },
    )
    rejected = client.get(
        "/webhooks/whatsapp",
        query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "token-errado",
            "hub.challenge": "123456",
        },
    )

    assert accepted.status_code == 200
    assert accepted.get_data(as_text=True) == "123456"
    assert rejected.status_code == 403


def test_invalid_signature_is_rejected_before_persistence(
    client, app, company_factory
):
    company = company_factory()
    db.session.add(
        WhatsAppIntegration(
            company_id=company.id,
            phone_number_id="phone-123",
            status="CONNECTED",
            is_active=True,
        )
    )
    db.session.commit()
    app.config["WHATSAPP_APP_SECRET"] = "meta-app-secret"
    raw = json.dumps(_message_payload("phone-123"), separators=(",", ":")).encode()

    response = client.post(
        "/webhooks/whatsapp",
        data=raw,
        content_type="application/json",
        headers={"X-Hub-Signature-256": "sha256=invalid"},
    )

    assert response.status_code == 401
    assert Message.query.count() == 0


def test_valid_message_is_stored_once_and_enqueued_once(
    client, app, company_factory
):
    company = company_factory()
    db.session.add(
        WhatsAppIntegration(
            company_id=company.id,
            phone_number_id="phone-456",
            status="CONNECTED",
            is_active=True,
        )
    )
    db.session.commit()
    app.config["WHATSAPP_APP_SECRET"] = "meta-app-secret"
    payload = _message_payload("phone-456")
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {"X-Hub-Signature-256": _signature("meta-app-secret", raw)}
    first = client.post(
        "/webhooks/whatsapp", data=raw, content_type="application/json", headers=headers
    )
    repeated = client.post(
        "/webhooks/whatsapp", data=raw, content_type="application/json", headers=headers
    )

    assert first.status_code == repeated.status_code == 200
    assert first.get_json()["queued"] == 0
    assert repeated.get_json()["queued"] == 0
    assert first.get_json()["outbox_pending"] == 1
    # Meta retries are acknowledged without attempting the same pending row
    # again; the periodic dispatcher owns broker recovery.
    assert repeated.get_json()["outbox_pending"] == 0
    assert Customer.query.filter_by(company_id=company.id).count() == 1
    assert Conversation.query.filter_by(company_id=company.id).count() == 1
    message = Message.query.filter_by(company_id=company.id).one()
    assert message.external_message_id == "wamid.001"
    assert message.content == "Tem camiseta preta tamanho M?"
    outbox = TaskOutbox.query.one()
    assert outbox.company_id == company.id
    assert outbox.task_name == "process_message"
    assert outbox.idempotency_key == f"process-message:{message.id}"
    assert outbox.payload_json == {"message_id": message.id}
    assert outbox.status == "PENDING"
