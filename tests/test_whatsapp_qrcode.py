"""QR Code da conexao WhatsApp via Evolution API."""

from __future__ import annotations

import base64

import pytest

from app.extensions import db
from app.models import WhatsAppIntegration
from app.services.exceptions import ExternalServiceError
from app.services.whatsapp_service import WhatsAppService
from backend.services.generate_whatsapp_qrcode_service import (
    GenerateWhatsAppQrCodeService,
)


def _integration(company_id: int, instance_name: str = "loja-qrcode"):
    integration = WhatsAppIntegration(
        company_id=company_id,
        instance_name=instance_name,
        status="PENDING",
        is_active=False,
    )
    db.session.add(integration)
    db.session.commit()
    return integration


def test_qrcode_endpoint_is_scoped_to_logged_in_company(
    client, tenant_user, login_as, monkeypatch
):
    _integration(tenant_user.company_id)
    login_as(tenant_user)
    calls = []

    def fake_execute(_service, company_id):
        calls.append(company_id)
        return {
            "connected": False,
            "instance_name": "loja-qrcode",
            "qr_code": "data:image/png;base64,iVBORw0KGgo=",
            "pairing_code": None,
        }

    monkeypatch.setattr(GenerateWhatsAppQrCodeService, "execute", fake_execute)
    response = client.post("/settings/whatsapp/qrcode", json={})

    assert response.status_code == 200
    assert response.get_json()["data"]["instance_name"] == "loja-qrcode"
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert calls == [tenant_user.company_id]


def test_agent_cannot_request_qrcode(client, user_factory, login_as):
    agent = user_factory(role="AGENT")
    _integration(agent.company_id)
    login_as(agent)

    response = client.post("/settings/whatsapp/qrcode", json={})

    assert response.status_code == 403


def test_whatsapp_page_shows_instance_and_qrcode_actions(
    client, tenant_user, login_as
):
    integration = _integration(tenant_user.company_id)
    integration.display_name = "http://localhost:8080"
    db.session.commit()
    login_as(tenant_user)

    response = client.get("/settings/whatsapp")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<h2>loja-qrcode</h2>" in html
    assert "Exibir QR Code" in html
    assert "Imprimir QR Code" in html
    assert 'id="whatsapp-qr"' in html


def test_service_normalizes_png_data_url(app, company_factory, monkeypatch):
    company = company_factory()
    _integration(company.id, "loja-png")
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nqr-data").decode()
    evolution_service = WhatsAppService(api_url="http://evolution", api_key="test-key")
    monkeypatch.setattr(
        evolution_service,
        "request_qr_code",
        lambda instance_name: {
            "base64": encoded,
            "pairingCode": "1234-5678",
        },
    )
    service = GenerateWhatsAppQrCodeService(evolution_service)

    result = service.execute(company.id)

    assert result["qr_code"] == f"data:image/png;base64,{encoded}"
    assert result["pairing_code"] == "1234-5678"


def test_service_rejects_non_png_qrcode(app, company_factory, monkeypatch):
    company = company_factory()
    _integration(company.id, "loja-invalid")
    evolution_service = WhatsAppService(api_url="http://evolution", api_key="test-key")
    monkeypatch.setattr(
        evolution_service,
        "request_qr_code",
        lambda instance_name: {
            "base64": base64.b64encode(b"not-a-png").decode()
        },
    )
    service = GenerateWhatsAppQrCodeService(evolution_service)

    with pytest.raises(ExternalServiceError, match="formato invalido"):
        service.execute(company.id)


def test_whatsapp_model_owns_basic_persistence(app, company_factory):
    company = company_factory()
    integration = WhatsAppIntegration(
        company_id=company.id,
        instance_name="loja-model-crud",
        status="PENDING",
        is_active=False,
    ).salvar()

    assert WhatsAppIntegration.buscar_por_id(integration.id) is integration
    assert integration in WhatsAppIntegration.listar_todos()

    integration.atualizar(display_name="Loja principal")
    assert WhatsAppIntegration.buscar_por_id(integration.id).display_name == "Loja principal"

    integration_id = integration.id
    integration.deletar()
    assert WhatsAppIntegration.buscar_por_id(integration_id) is None
