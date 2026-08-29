"""Configuracoes da IA e integracao WhatsApp via Evolution API."""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AISettings, WhatsAppIntegration
from app.controllers.http import coerce_bool, failure, model_dict, payload, record_audit, success
from app.services.exceptions import DomainError
from app.services.whatsapp import (
    CheckWhatsAppConnectionService,
    DisconnectWhatsAppService,
    SendWhatsAppTextService,
)
from app.services.whatsapp_service import WhatsAppGateway
from app.tenant import current_company_id, roles_required


bp = Blueprint("settings", __name__, url_prefix="/settings")


def _ai_settings(company_id: int) -> AISettings:
    settings = AISettings.for_company(company_id).one_or_none()
    if settings is None:
        settings = AISettings(company_id=company_id)
        db.session.add(settings)
        db.session.commit()
    return settings


@bp.get("/ai")
@login_required
def ai():
    settings = _ai_settings(current_company_id())
    view = {
        "name": settings.assistant_name,
        "personality": settings.personality or "helpful",
        "tone": settings.tone,
        "welcome_message": settings.greeting_message or "",
        "offline_message": settings.after_hours_message or "",
        "rules": [line for line in (settings.rules or "").splitlines() if line.strip()],
        "commercial_instructions": settings.commercial_instructions or "",
        "transfer_message": settings.transfer_instructions or "",
        "model_label": settings.model or current_app.config["GROQ_MODEL"],
        "enabled": settings.is_enabled,
    }
    return render_template("settings/ai.html", settings=settings, ai_settings=view)


@bp.post("/ai")
@login_required
@roles_required("ADMIN", "OWNER")
def save_ai():
    settings = _ai_settings(current_company_id())
    data = payload()
    aliases = {
        "name": "assistant_name",
        "welcome_message": "greeting_message",
        "offline_message": "after_hours_message",
        "transfer_message": "transfer_instructions",
    }
    for source, target in aliases.items():
        if source in data and target not in data:
            data[target] = data[source]
    submitted_rules = request.form.getlist("rules[]")
    if submitted_rules:
        data["rules"] = "\n".join(
            rule.strip() for rule in submitted_rules if rule.strip()
        )
    text_fields = {
        "assistant_name": 100,
        "personality": 4000,
        "tone": 80,
        "greeting_message": 4000,
        "after_hours_message": 4000,
        "rules": 8000,
        "commercial_instructions": 8000,
        "transfer_instructions": 4000,
    }
    for field, limit in text_fields.items():
        if field in data:
            setattr(settings, field, str(data[field]).strip()[:limit] or None)
    try:
        if "temperature" in data:
            settings.temperature = min(2.0, max(0.0, float(data["temperature"])))
        if "max_tokens" in data:
            settings.max_tokens = min(4096, max(100, int(data["max_tokens"])))
        if "history_limit" in data:
            settings.history_limit = min(100, max(5, int(data["history_limit"])))
        if "summary_threshold" in data:
            settings.summary_threshold = min(500, max(20, int(data["summary_threshold"])))
    except (ValueError, TypeError):
        return failure("Valores numericos invalidos.", status=422)
    if "is_enabled" in data or "enabled" in data:
        settings.is_enabled = coerce_bool(data.get("is_enabled", data.get("enabled")))
    if "auto_reply_enabled" in data:
        settings.auto_reply_enabled = coerce_bool(data.get("auto_reply_enabled"))
    # O modelo e controlado no backend para impedir troca de provedor pelo cliente.
    settings.model = current_app.config["GROQ_MODEL"]
    record_audit("ai_settings.update", settings, {field: "updated" for field in data})
    db.session.commit()
    return success("Configuracoes da IA salvas.", endpoint="settings.ai")


@bp.get("/whatsapp")
@login_required
def whatsapp():
    integration = WhatsAppIntegration.for_company(current_company_id()).one_or_none()
    webhook_url = current_app.config.get("EVOLUTION_WEBHOOK_URL") or (
        f"{current_app.config['APP_URL'].rstrip('/')}/webhooks/evolution"
    )
    safe_integration = None
    if integration:
        safe_integration = {
            **model_dict(
                integration,
                "id",
                "instance_name",
                "display_name",
                "status",
                "is_active",
                "last_webhook_at",
                "last_error",
                "updated_at",
            ),
            "connected": integration.status == "CONNECTED" and integration.is_active,
            "last_webhook_label": (
                integration.last_webhook_at.strftime("%d/%m/%Y %H:%M")
                if integration.last_webhook_at
                else "ainda nao recebido"
            ),
            "webhook_verified": bool(integration.last_webhook_at),
            "webhook_url": webhook_url,
        }
    evolution_configured = bool(
        current_app.config.get("EVOLUTION_API_URL") or os.getenv("EVOLUTION_API_URL")
    )
    return render_template(
        "settings/whatsapp.html",
        integration=integration,
        integration_safe=safe_integration,
        whatsapp_integration=safe_integration or {},
        webhook_url=webhook_url,
        evolution_configured=evolution_configured,
    )


@bp.post("/whatsapp")
@login_required
@roles_required("ADMIN", "OWNER")
def save_whatsapp():
    company_id = current_company_id()
    data = payload()
    instance_name = str(data.get("instance_name", "")).strip()
    try:
        instance_name = WhatsAppGateway.validate_instance_name(instance_name)
    except DomainError as exc:
        return failure(exc.message, status=422)
    integration = WhatsAppIntegration.for_company(company_id).one_or_none()
    if integration is None:
        integration = WhatsAppIntegration(company_id=company_id, instance_name=instance_name)
        db.session.add(integration)
    integration.instance_name = instance_name
    integration.display_name = str(data.get("display_name", "")).strip()[:100] or None
    # Instancia nova fica pendente ate a verificacao de conexao ser feita.
    integration.is_active = False
    integration.status = "PENDING"
    integration.last_error = None
    try:
        db.session.flush()
        record_audit(
            "whatsapp_integration.update",
            integration,
            {"instance_name": integration.instance_name},
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return failure("Este nome de instancia ja esta em uso.", status=409)
    return success(
        "Configuracao salva. Verifique a conexao para ativar a integracao.",
        endpoint="settings.whatsapp",
    )


@bp.post("/whatsapp/check")
@login_required
@roles_required("ADMIN", "OWNER")
def check_whatsapp():
    try:
        result = CheckWhatsAppConnectionService().execute(current_company_id())
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    return success("Conexao com a Evolution API validada.", data=result)


@bp.post("/whatsapp/test")
@login_required
@roles_required("ADMIN", "OWNER")
def test_whatsapp():
    data = payload()
    recipient = str(data.get("to", data.get("phone", ""))).strip()
    if not recipient:
        return failure("Informe um numero de destino para o teste.", status=422)
    try:
        result = SendWhatsAppTextService().execute(
            current_company_id(),
            to=recipient,
            text=str(data.get("message", "Teste de conexao do AutoFlow."))[:4096],
        )
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    return success("Mensagem de teste enviada.", data={"evolution": result})


@bp.post("/whatsapp/disconnect")
@login_required
@roles_required("ADMIN", "OWNER")
def disconnect_whatsapp():
    company_id = current_company_id()
    try:
        DisconnectWhatsAppService().execute(company_id)
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    record_audit(
        "whatsapp_integration.disconnect",
        WhatsAppIntegration.for_company(company_id).one(),
    )
    return success("WhatsApp desconectado.", endpoint="settings.whatsapp")


class SettingsController:
    """HTTP controller for AI and WhatsApp settings."""

    ai = staticmethod(ai)
    save_ai = staticmethod(save_ai)
    whatsapp = staticmethod(whatsapp)
    save_whatsapp = staticmethod(save_whatsapp)
    check_whatsapp = staticmethod(check_whatsapp)
    test_whatsapp = staticmethod(test_whatsapp)
    disconnect_whatsapp = staticmethod(disconnect_whatsapp)


bp.view_functions.update(
    {
        "ai": SettingsController.ai,
        "save_ai": SettingsController.save_ai,
        "whatsapp": SettingsController.whatsapp,
        "save_whatsapp": SettingsController.save_whatsapp,
        "check_whatsapp": SettingsController.check_whatsapp,
        "test_whatsapp": SettingsController.test_whatsapp,
        "disconnect_whatsapp": SettingsController.disconnect_whatsapp,
    }
)
