"""Autenticação, idempotência e enqueue do webhook Evolution API v2."""

import json

from app.extensions import db
from app.models import (
    Conversation,
    Customer,
    Message,
    TaskOutbox,
    WhatsAppIntegration,
)
from app.services.whatsapp_service import WhatsAppService


def _evolution_payload(instance_name: str, message_id: str = "msg-001") -> dict:
    return {
        "event": "messages.upsert",
        "instance": instance_name,
        "apikey": "test-evolution-key",
        "data": {
            "key": {
                "remoteJid": "5511999993333@s.whatsapp.net",
                "fromMe": False,
                "id": message_id,
            },
            "pushName": "Cliente Evolution",
            "messageTimestamp": 1893459600,
            "message": {"conversation": "Tem camiseta preta tamanho M?"},
        },
    }


def test_invalid_apikey_is_rejected(client, app, company_factory):
    """Webhook com apikey incorreta deve retornar 401."""
    company = company_factory()
    db.session.add(
        WhatsAppIntegration(
            company_id=company.id,
            instance_name="loja-teste",
            status="CONNECTED",
            is_active=True,
        )
    )
    db.session.commit()
    app.config["EVOLUTION_API_KEY"] = "correct-key"

    payload = _evolution_payload("loja-teste")
    payload["apikey"] = "wrong-key"
    raw = json.dumps(payload, separators=(",", ":")).encode()

    response = client.post(
        "/webhooks/evolution",
        data=raw,
        content_type="application/json",
    )

    assert response.status_code == 401
    assert Message.query.count() == 0


def test_instance_apikey_is_validated_against_evolution(monkeypatch):
    service = WhatsAppService(api_url="http://evolution", api_key="global-key")
    calls = []

    def fake_request(method, path, payload=None, *, api_key=None):
        calls.append((method, path, api_key))
        return {"instance": {"state": "open"}}

    monkeypatch.setattr(service, "_request", fake_request)

    assert service.verify_webhook(
        {"instance": "loja-principal", "apikey": "instance-token"}
    )
    assert calls == [
        (
            "GET",
            "instance/connectionState/loja-principal",
            "instance-token",
        )
    ]


def test_missing_instance_is_rejected(client, app):
    """Webhook sem nome de instância deve retornar 400."""
    app.config["EVOLUTION_API_KEY"] = "test-key"
    payload = {"event": "messages.upsert", "apikey": "test-key"}
    raw = json.dumps(payload, separators=(",", ":")).encode()

    response = client.post(
        "/webhooks/evolution",
        data=raw,
        content_type="application/json",
    )

    assert response.status_code == 400


def test_valid_message_is_stored_once_and_enqueued_once(
    client, app, company_factory
):
    """Mensagem válida deve criar Customer, Conversation, Message e TaskOutbox
    na primeira chamada e ser idempotente nas subsequentes."""
    company = company_factory()
    db.session.add(
        WhatsAppIntegration(
            company_id=company.id,
            instance_name="loja-principal",
            status="CONNECTED",
            is_active=True,
        )
    )
    db.session.commit()
    app.config["EVOLUTION_API_KEY"] = "test-evolution-key"

    payload = _evolution_payload("loja-principal")
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()

    first = client.post(
        "/webhooks/evolution",
        data=raw,
        content_type="application/json",
    )
    repeated = client.post(
        "/webhooks/evolution",
        data=raw,
        content_type="application/json",
    )

    assert first.status_code == repeated.status_code == 200
    first_json = first.get_json()
    repeated_json = repeated.get_json()

    # Primeira chamada cria e enfileira; segunda reconhece como duplicada.
    assert first_json["events"] == 1
    assert first_json["outbox_pending"] == 1
    assert repeated_json["events"] == 1
    assert repeated_json["outbox_pending"] == 0

    assert Customer.query.filter_by(company_id=company.id).count() == 1
    assert Conversation.query.filter_by(company_id=company.id).count() == 1
    message = Message.query.filter_by(company_id=company.id).one()
    assert message.external_message_id == "msg-001"
    assert message.content == "Tem camiseta preta tamanho M?"
    outbox = TaskOutbox.query.one()
    assert outbox.company_id == company.id
    assert outbox.task_name == "process_message"
    assert outbox.idempotency_key == f"process-message:{message.id}"
    assert outbox.payload_json == {"message_id": message.id}
    assert outbox.status == "PENDING"


def test_group_messages_are_ignored(client, app, company_factory):
    """Mensagens vindas de grupos (@g.us) devem ser silenciosamente ignoradas."""
    company = company_factory()
    db.session.add(
        WhatsAppIntegration(
            company_id=company.id,
            instance_name="loja-grupo",
            status="CONNECTED",
            is_active=True,
        )
    )
    db.session.commit()
    app.config["EVOLUTION_API_KEY"] = "test-evolution-key"

    payload = _evolution_payload("loja-grupo")
    payload["data"]["key"]["remoteJid"] = "120363000000000000@g.us"
    raw = json.dumps(payload, separators=(",", ":")).encode()

    response = client.post(
        "/webhooks/evolution",
        data=raw,
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.get_json()["events"] == 0
    assert Message.query.count() == 0


def test_from_me_messages_are_ignored(client, app, company_factory):
    """Mensagens enviadas pelo próprio número (fromMe=True) devem ser ignoradas."""
    company = company_factory()
    db.session.add(
        WhatsAppIntegration(
            company_id=company.id,
            instance_name="loja-me",
            status="CONNECTED",
            is_active=True,
        )
    )
    db.session.commit()
    app.config["EVOLUTION_API_KEY"] = "test-evolution-key"

    payload = _evolution_payload("loja-me")
    payload["data"]["key"]["fromMe"] = True
    raw = json.dumps(payload, separators=(",", ":")).encode()

    response = client.post(
        "/webhooks/evolution",
        data=raw,
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.get_json()["events"] == 0
    assert Message.query.count() == 0
