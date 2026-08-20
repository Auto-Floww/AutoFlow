"""Configuracoes da IA e integracao oficial com WhatsApp."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AISettings, WhatsAppIntegration
from app.routes.helpers import coerce_bool, failure, model_dict, payload, record_audit, success
from app.security import encrypt_secret
from app.services.exceptions import DomainError
from app.services.whatsapp_service import WhatsAppService
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
    safe_integration = None
    if integration:
        safe_integration = {
            **model_dict(
                integration,
                "id",
                "display_phone_number",
                "phone_number_id",
                "business_account_id",
                "status",
                "is_active",
                "last_webhook_at",
                "last_error",
                "updated_at",
            ),
            "has_access_token": bool(
                integration.access_token_encrypted
                or current_app.config.get("WHATSAPP_ACCESS_TOKEN")
            ),
            "has_app_secret": bool(
                integration.app_secret_encrypted
                or current_app.config.get("WHATSAPP_APP_SECRET")
            ),
            "connected": integration.status == "CONNECTED" and integration.is_active,
            "phone_number_id_masked": integration.phone_number_id,
            "business_account_id_masked": integration.business_account_id or "",
            "last_webhook_label": (
                integration.last_webhook_at.strftime("%d/%m/%Y %H:%M")
                if integration.last_webhook_at
                else "ainda nao recebido"
            ),
            "webhook_verified": bool(integration.last_webhook_at),
            "webhook_url": f"{current_app.config['APP_URL'].rstrip('/')}/webhooks/whatsapp",
        }
    return render_template(
        "settings/whatsapp.html",
        integration=integration,
        integration_safe=safe_integration,
        whatsapp_integration=safe_integration or {},
        webhook_url=f"{current_app.config['APP_URL'].rstrip('/')}/webhooks/whatsapp",
        verify_token_configured=bool(current_app.config.get("WHATSAPP_VERIFY_TOKEN")),
    )


@bp.post("/whatsapp")
@login_required
@roles_required("ADMIN", "OWNER")
def save_whatsapp():
    company_id = current_company_id()
    data = payload()
    phone_number_id = str(data.get("phone_number_id", "")).strip()
    if not phone_number_id:
        return failure("Informe o Phone Number ID da Meta.", status=422)
    integration = WhatsAppIntegration.for_company(company_id).one_or_none()
    if integration is None:
        integration = WhatsAppIntegration(company_id=company_id, phone_number_id=phone_number_id)
        db.session.add(integration)
    integration.phone_number_id = phone_number_id[:100]
    integration.display_phone_number = str(data.get("display_phone_number", "")).strip()[:32] or None
    integration.business_account_id = str(data.get("business_account_id", "")).strip()[:100] or None
    # Credenciais novas só ficam aptas a receber/enviar após validação real na Meta.
    integration.is_active = False
    if data.get("access_token"):
        integration.access_token_encrypted = encrypt_secret(str(data["access_token"]).strip())
    if data.get("app_secret"):
        integration.app_secret_encrypted = encrypt_secret(str(data["app_secret"]).strip())
    integration.status = "PENDING"
    integration.last_error = None
    try:
        db.session.flush()
        record_audit(
            "whatsapp_integration.update",
            integration,
            {
                "phone_number_id": integration.phone_number_id,
                "business_account_id": integration.business_account_id,
                "credentials": "updated" if data.get("access_token") or data.get("app_secret") else "unchanged",
            },
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return failure("Este numero ja esta conectado a outra empresa.", status=409)
    return success(
        "Configuracao salva. Teste a conexao para ativar a integracao.",
        endpoint="settings.whatsapp",
    )


@bp.post("/whatsapp/check")
@login_required
@roles_required("ADMIN", "OWNER")
def check_whatsapp():
    try:
        result = WhatsAppService().check_connection(current_company_id())
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    return success("Conexao com a Meta validada.", data=result)


@bp.post("/whatsapp/test")
@login_required
@roles_required("ADMIN", "OWNER")
def test_whatsapp():
    data = payload()
    recipient = str(data.get("to", data.get("phone", ""))).strip()
    if not recipient:
        return failure("Informe um numero de destino para o teste.", status=422)
    try:
        result = WhatsAppService().send_text(
            current_company_id(),
            to=recipient,
            text=str(data.get("message", "Teste de conexao do AutoFlow."))[:4096],
        )
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    return success("Mensagem de teste enviada.", data={"meta": result})


@bp.post("/whatsapp/disconnect")
@login_required
@roles_required("ADMIN", "OWNER")
def disconnect_whatsapp():
    integration = WhatsAppIntegration.for_company(current_company_id()).one_or_none()
    if integration is None:
        return failure("Integracao nao encontrada.", status=404)
    integration.is_active = False
    integration.status = "DISCONNECTED"
    record_audit("whatsapp_integration.disconnect", integration)
    db.session.commit()
    return success("WhatsApp desconectado.", endpoint="settings.whatsapp")
