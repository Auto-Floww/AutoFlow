"""Durabilidade, recuperação e allow-list do transactional outbox."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import Message, TaskOutbox, WhatsAppIntegration
from app.models.base import utcnow
from app.models.outbox import OUTBOX_TASK_NAMES
from app.services.exceptions import ValidationError
from app.services.outbox_service import OutboxService
from app.tasks.ai_tasks import dispatch_task_outbox


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _message_payload(phone_number_id: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-outbox",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [
                                {
                                    "wa_id": "5511988881111",
                                    "profile": {"name": "Cliente Outbox"},
                                }
                            ],
                            "messages": [
                                {
                                    "from": "5511988881111",
                                    "id": "wamid.outbox-recovery",
                                    "timestamp": "1893459600",
                                    "type": "text",
                                    "text": {"body": "Mensagem durável"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def test_webhook_survives_broker_failure_and_beat_recovers(
    client, app, company_factory, monkeypatch
):
    company = company_factory()
    integration = WhatsAppIntegration(
        company_id=company.id,
        phone_number_id="phone-outbox",
        status="CONNECTED",
        is_active=True,
    )
    db.session.add(integration)
    db.session.commit()
    app.config.update(
        WHATSAPP_APP_SECRET="meta-outbox-secret",
        OUTBOX_IMMEDIATE_DISPATCH=True,
    )
    raw = json.dumps(
        _message_payload(integration.phone_number_id),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()

    failed_publish_options = []

    class BrokerUnavailable:
        @staticmethod
        def apply_async(**options):
            failed_publish_options.append(options)
            raise ConnectionError("redis is unavailable")

    monkeypatch.setattr(
        OutboxService,
        "_resolve_task",
        staticmethod(lambda task_name: BrokerUnavailable),
    )
    response = client.post(
        "/webhooks/whatsapp",
        data=raw,
        content_type="application/json",
        headers={
            "X-Hub-Signature-256": _signature("meta-outbox-secret", raw)
        },
    )

    assert response.status_code == 200
    assert response.get_json()["received"] is True
    assert response.get_json()["queued"] == 0
    assert response.get_json()["outbox_pending"] == 1
    message = Message.query.one()
    outbox = TaskOutbox.query.one()
    assert outbox.task_name == "process_message"
    assert outbox.payload_json == {"message_id": message.id}
    assert outbox.status == "PENDING"
    assert outbox.attempts == 1
    assert outbox.error == "ConnectionError: broker dispatch failed"
    assert failed_publish_options[0]["retry"] is False
    assert failed_publish_options[0]["retry_policy"]["max_retries"] == 0

    # Make the failed row due now, as if Celery beat reached its backoff window.
    outbox.available_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    recovered_publish_options = []

    class BrokerRecovered:
        @staticmethod
        def apply_async(**options):
            recovered_publish_options.append(options)

    monkeypatch.setattr(
        OutboxService,
        "_resolve_task",
        staticmethod(lambda task_name: BrokerRecovered),
    )
    result = dispatch_task_outbox.run()

    db.session.expire_all()
    recovered = db.session.get(TaskOutbox, outbox.id)
    assert result == {"selected": 1, "dispatched": 1, "pending": 0}
    assert recovered.status == "DISPATCHED"
    assert recovered.attempts == 2
    assert recovered.dispatched_at is not None
    assert recovered.error is None
    assert recovered_publish_options == [
        {
            "kwargs": {"message_id": message.id},
            "task_id": f"autoflow-outbox-{outbox.id}",
            "ignore_result": True,
            "retry": False,
            "retry_policy": {"max_retries": 0, "interval_start": 0},
        }
    ]


def test_outbox_allow_list_payload_and_idempotency_contract(app):
    assert set(OUTBOX_TASK_NAMES) == {
        "process_message",
        "send_whatsapp_message",
        "generate_summary",
        "password_reset_email",
        "process_appointment",
        "send_notification",
    }
    entry = OutboxService.enqueue(
        "process_appointment",
        {"appointment_id": 12, "event": "created"},
        idempotency_key="appointment-task:12:created",
    )
    duplicate = OutboxService.enqueue(
        "process_appointment",
        {"appointment_id": 12, "event": "created"},
        idempotency_key="appointment-task:12:created",
    )
    assert duplicate.id == entry.id

    with pytest.raises(ValidationError, match="not allowed"):
        OutboxService.enqueue(
            "arbitrary.import.path",
            {},
            idempotency_key="unsafe-task",
        )
    with pytest.raises(ValidationError, match="unsupported fields"):
        OutboxService.enqueue(
            "process_message",
            {"message_id": 1, "secret_extra_argument": "forbidden"},
            idempotency_key="unsafe-payload",
        )


def test_outbox_tasks_are_registered_on_the_application_celery(app):
    registered = app.extensions["celery"].tasks

    assert "app.tasks.password_reset_email" in registered
    assert "app.tasks.dispatch_task_outbox" in registered
