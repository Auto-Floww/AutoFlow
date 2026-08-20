"""Utilitarios compartilhados pelos blueprints."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import flash, jsonify, redirect, request, url_for
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def company_local(value: datetime | None, timezone_name: str) -> datetime | None:
    """Convert a naive UTC database timestamp to a company's display timezone."""

    if value is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(timezone)


def wants_json() -> bool:
    return request.is_json or request.path.startswith("/api/") or request.headers.get(
        "X-Requested-With"
    ) == "XMLHttpRequest"


def payload() -> dict[str, Any]:
    if request.is_json:
        return request.get_json(silent=True) or {}
    data = request.form.to_dict()
    # O token ja foi validado pelo Flask-WTF e nunca pertence ao dominio.
    data.pop("csrf_token", None)
    return data


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "sim"}


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def serializable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return serializable(value)


def model_dict(instance, *fields: str) -> dict[str, Any]:
    return {field: serializable(getattr(instance, field, None)) for field in fields}


def success(
    message: str,
    *,
    data: dict[str, Any] | None = None,
    endpoint: str | None = None,
    status: int = 200,
    **url_values,
):
    if wants_json():
        response = {"ok": True, "message": message}
        if data is not None:
            response["data"] = data
        return jsonify(response), status
    flash(message, "success")
    return redirect(url_for(endpoint, **url_values) if endpoint else request.referrer or "/")


def failure(
    message: str,
    *,
    errors: Any = None,
    endpoint: str | None = None,
    status: int = 400,
    **url_values,
):
    if wants_json():
        response = {"ok": False, "message": message}
        if errors is not None:
            response["errors"] = errors
        return jsonify(response), status
    flash(message, "error")
    return redirect(url_for(endpoint, **url_values) if endpoint else request.referrer or "/")


def record_audit(action: str, entity, changes: dict[str, Any] | None = None) -> None:
    """Anexa um registro append-only a mesma transacao da mudanca."""

    company_id = getattr(current_user, "company_id", None) or getattr(
        entity, "company_id", None
    )
    if not company_id:
        return
    db.session.add(
        AuditLog(
            company_id=company_id,
            actor_user_id=getattr(current_user, "id", None),
            action=action,
            entity_type=entity.__class__.__name__,
            entity_id=str(getattr(entity, "id", "")) or None,
            changes_json=json_safe(changes or {}),
            # remote_addr só deve ser reescrito por um ProxyFix configurado no deploy;
            # aceitar X-Forwarded-For diretamente tornaria a trilha falsificável.
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string[:500],
        )
    )
