"""Regressões de isolamento, sessão e autenticação de integrações."""

import hashlib
import json
import secrets
from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import CompanyMember, Conversation, Customer, Message, WhatsAppIntegration
from app.models.base import utcnow


def test_disabled_membership_revokes_an_existing_session(
    client, login_as, tenant_user
):
    login_as(tenant_user)
    membership = CompanyMember.query.filter_by(
        company_id=tenant_user.active_company_id, user_id=tenant_user.id
    ).one()
    membership.status = "DISABLED"
    db.session.commit()

    response = client.get("/customers", headers={"Accept": "application/json"})

    assert response.status_code == 401


def test_suspended_company_revokes_an_existing_session(client, login_as, tenant_user):
    login_as(tenant_user)
    tenant_user.active_company.status = "SUSPENDED"
    db.session.commit()

    response = client.get("/customers", headers={"Accept": "application/json"})

    assert response.status_code == 401


def test_password_change_invalidates_previously_issued_session(
    client, login_as, tenant_user
):
    login_as(tenant_user)
    token = secrets.token_urlsafe(32)
    tenant_user.reset_token_hash = hashlib.sha256(token.encode()).hexdigest()
    tenant_user.reset_token_expires_at = utcnow() + timedelta(minutes=30)
    db.session.commit()

    changed = client.post(
        f"/reset-password/{token}",
        json={"password": "SenhaNova456!", "confirm_password": "SenhaNova456!"},
    )

    assert changed.status_code == 200
    assert client.get("/dashboard").status_code == 302


def test_one_tenant_secret_cannot_authorize_another_tenant_change(
    client, app, company_factory
):
    company_a = company_factory()
    company_b = company_factory()
    db.session.add_all(
        [
            WhatsAppIntegration(
                company_id=company_a.id,
                instance_name="phone-a",
                status="CONNECTED",
                is_active=True,
            ),
            WhatsAppIntegration(
                company_id=company_b.id,
                instance_name="phone-b",
                status="CONNECTED",
                is_active=True,
            ),
        ]
    )
    db.session.commit()
    app.config["EVOLUTION_API_KEY"] = "installation-key"
    body = {
        "event": "messages.upsert",
        "instance": "phone-b",
        "apikey": "invalid-installation-key",
        "data": {
            "key": {
                "remoteJid": "5511999990001@s.whatsapp.net",
                "fromMe": False,
                "id": "b-1",
            },
            "message": {"conversation": "Nao autorizada"},
        },
    }
    raw = json.dumps(body, separators=(",", ":")).encode()

    response = client.post(
        "/webhooks/evolution",
        data=raw,
        content_type="application/json",
    )

    assert response.status_code == 401
    assert Message.query.count() == 0


def test_agent_cannot_take_or_message_a_colleagues_conversation(
    client, login_as, tenant_user, user_factory
):
    colleague = user_factory(company=tenant_user.active_company, role="AGENT")
    customer = Customer(
        company_id=tenant_user.company_id,
        name="Cliente",
        phone="+5511999997777",
        phone_normalized="5511999997777",
    )
    db.session.add(customer)
    db.session.flush()
    conversation = Conversation(
        company_id=tenant_user.company_id,
        customer_id=customer.id,
        assigned_user_id=tenant_user.id,
        ai_status="PAUSED",
    )
    db.session.add(conversation)
    db.session.commit()
    login_as(colleague)

    assert client.post(f"/conversations/{conversation.id}/assume", json={}).status_code == 409
    assert (
        client.post(
            f"/conversations/{conversation.id}/send", json={"body": "Mensagem indevida"}
        ).status_code
        == 403
    )
    assert client.post(f"/conversations/{conversation.id}/return-to-ai", json={}).status_code == 403
    assert Message.query.count() == 0


def test_unknown_runtime_environment_fails_closed(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "prod-typo")
    with pytest.raises(RuntimeError, match="Ambiente desconhecido"):
        create_app()
