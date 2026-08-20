"""Cost/backpressure regression tests for inbound WhatsApp messages."""

from __future__ import annotations

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


def _payload(phone_number_id: str, message_id: str, sender: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-quota",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [
                                {
                                    "wa_id": sender,
                                    "profile": {"name": f"Cliente {sender[-4:]}"},
                                }
                            ],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "timestamp": "1893459600",
                                    "type": "text",
                                    "text": {"body": "Mensagem sujeita a quota"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _post(client, secret: str, phone_number_id: str, message_id: str, sender: str):
    raw = json.dumps(
        _payload(phone_number_id, message_id, sender),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/whatsapp",
        data=raw,
        content_type="application/json",
        headers={"X-Hub-Signature-256": f"sha256={digest}"},
    )


def _integration(company, phone_number_id: str, *, status: str = "CONNECTED"):
    integration = WhatsAppIntegration(
        company_id=company.id,
        phone_number_id=phone_number_id,
        status=status,
        is_active=True,
    )
    db.session.add(integration)
    db.session.commit()
    return integration


def _configure(app, *, hourly: int, sender_minute: int) -> str:
    secret = "quota-app-secret"
    app.config.update(
        WHATSAPP_APP_SECRET=secret,
        OUTBOX_IMMEDIATE_DISPATCH=False,
        AI_INBOUND_HOURLY_LIMIT=hourly,
        AI_SENDER_MINUTE_LIMIT=sender_minute,
    )
    return secret


def test_company_hourly_limit_is_tenant_scoped(
    client, app, company_factory
):
    secret = _configure(app, hourly=1, sender_minute=20)
    company_a = company_factory(name="Tenant A")
    company_b = company_factory(name="Tenant B")
    _integration(company_a, "phone-tenant-a")
    _integration(company_b, "phone-tenant-b")

    accepted_a = _post(
        client, secret, "phone-tenant-a", "wamid.a-1", "5511999990001"
    )
    accepted_b = _post(
        client, secret, "phone-tenant-b", "wamid.b-1", "5511999990002"
    )
    rejected_a = _post(
        client, secret, "phone-tenant-a", "wamid.a-2", "5511999990003"
    )

    assert accepted_a.status_code == accepted_b.status_code == 200
    assert rejected_a.status_code == 429
    assert rejected_a.headers["Retry-After"] == "3600"
    assert rejected_a.get_json()["details"]["scope"] == "company_hour"
    assert Message.query.filter_by(company_id=company_a.id).count() == 1
    assert Message.query.filter_by(company_id=company_b.id).count() == 1
    assert TaskOutbox.query.filter_by(company_id=company_a.id).count() == 1
    assert Customer.query.filter_by(company_id=company_a.id).count() == 1


def test_sender_minute_limit_does_not_block_another_sender(
    client, app, company_factory
):
    secret = _configure(app, hourly=10, sender_minute=1)
    company = company_factory()
    _integration(company, "phone-sender-limit")

    first = _post(
        client, secret, "phone-sender-limit", "wamid.sender-1", "5511999991001"
    )
    rejected = _post(
        client, secret, "phone-sender-limit", "wamid.sender-2", "5511999991001"
    )
    other_sender = _post(
        client, secret, "phone-sender-limit", "wamid.sender-3", "5511999991002"
    )

    assert first.status_code == other_sender.status_code == 200
    assert rejected.status_code == 429
    assert rejected.headers["Retry-After"] == "60"
    assert rejected.get_json()["details"]["scope"] == "sender_minute"
    assert Message.query.filter_by(company_id=company.id).count() == 2
    assert Customer.query.filter_by(company_id=company.id).count() == 2
    assert Conversation.query.filter_by(company_id=company.id).count() == 2
    assert TaskOutbox.query.filter_by(company_id=company.id).count() == 2


def test_duplicate_is_idempotent_and_does_not_consume_quota(
    client, app, company_factory
):
    secret = _configure(app, hourly=1, sender_minute=1)
    company = company_factory()
    _integration(company, "phone-idempotent")

    first = _post(
        client, secret, "phone-idempotent", "wamid.duplicate", "5511999992001"
    )
    duplicate = _post(
        client, secret, "phone-idempotent", "wamid.duplicate", "5511999992001"
    )
    over_limit = _post(
        client, secret, "phone-idempotent", "wamid.new", "5511999992001"
    )

    assert first.status_code == duplicate.status_code == 200
    assert duplicate.get_json()["queued"] == 0
    assert over_limit.status_code == 429
    assert Message.query.filter_by(company_id=company.id).count() == 1
    assert TaskOutbox.query.filter_by(company_id=company.id).count() == 1
    assert Customer.query.filter_by(company_id=company.id).count() == 1
    assert Conversation.query.filter_by(company_id=company.id).count() == 1


def test_pending_integration_is_rejected_before_persistence(
    client, app, company_factory
):
    secret = _configure(app, hourly=300, sender_minute=30)
    company = company_factory()
    _integration(company, "phone-pending", status="PENDING")

    response = _post(
        client, secret, "phone-pending", "wamid.pending", "5511999993001"
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_integration_scope"
    assert Message.query.count() == 0
    assert Customer.query.count() == 0
    assert Conversation.query.count() == 0
    assert TaskOutbox.query.count() == 0
