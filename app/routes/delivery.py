"""Regras de entrega e retirada por empresa."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Company, DeliveryRule
from app.routes.helpers import coerce_bool, failure, model_dict, payload, record_audit, success
from app.tenant import current_company_id, roles_required, tenant_get_or_404
from app.services.delivery_service import DeliveryService
from app.services.exceptions import DomainError


bp = Blueprint("delivery", __name__, url_prefix="/delivery")


def _decimal(value) -> Decimal:
    raw = str(value or "0").replace("R$", "").replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        number = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Valor monetario invalido") from exc
    if number < 0:
        raise ValueError("Valor nao pode ser negativo")
    return number


def _postal(value) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))[:8]
    return digits or None


def _apply(rule: DeliveryRule, data: dict) -> None:
    rule.name = str(data.get("name", rule.name or "Entrega")).strip()[:160] or "Entrega"
    rule.city = str(data.get("city", rule.city or "")).strip()[:120] or None
    rule.neighborhood = str(data.get("neighborhood", rule.neighborhood or "")).strip()[:120] or None
    if "postal_code_start" in data or "cep_start" in data:
        rule.postal_code_start = _postal(data.get("postal_code_start", data.get("cep_start")))
    elif "zip_code_start" in data:
        rule.postal_code_start = _postal(data.get("zip_code_start"))
    if "postal_code_end" in data or "cep_end" in data:
        rule.postal_code_end = _postal(data.get("postal_code_end", data.get("cep_end")))
    elif "zip_code_end" in data:
        rule.postal_code_end = _postal(data.get("zip_code_end"))
    rule.price = _decimal(data.get("price", rule.price))
    rule.minimum_order = _decimal(data.get("minimum_order", rule.minimum_order))
    rule.free_shipping = coerce_bool(data.get("free_shipping"), False)
    rule.pickup_available = coerce_bool(data.get("pickup_available", data.get("pickup")), False)
    rule.is_active = coerce_bool(data.get("active", data.get("is_active")), True)
    rule.min_delivery_days = int(data.get("min_delivery_days", data.get("min_days", rule.min_delivery_days or 0)))
    rule.max_delivery_days = int(data.get("max_delivery_days", data.get("max_days", rule.max_delivery_days or 0)))
    rule.priority = int(data.get("priority", rule.priority or 100))
    if rule.min_delivery_days < 0 or rule.max_delivery_days < rule.min_delivery_days:
        raise ValueError("Prazo de entrega invalido")


def _data(rule: DeliveryRule) -> dict:
    return model_dict(
        rule,
        "id",
        "name",
        "city",
        "neighborhood",
        "postal_code_start",
        "postal_code_end",
        "price",
        "free_shipping",
        "minimum_order",
        "min_delivery_days",
        "max_delivery_days",
        "pickup_available",
        "is_active",
        "priority",
    )


@bp.get("")
@login_required
def index():
    company_id = current_company_id()
    rules = (
        DeliveryRule.for_company(company_id)
        .order_by(DeliveryRule.priority, DeliveryRule.city, DeliveryRule.neighborhood)
        .all()
    )
    rule_views = []
    for rule in rules:
        rule_views.append(
            SimpleNamespace(
                id=rule.id,
                name=rule.name,
                city=rule.city,
                neighborhood=rule.neighborhood,
                zip_code_start=rule.postal_code_start,
                zip_code_end=rule.postal_code_end,
                postal_code_start=rule.postal_code_start,
                postal_code_end=rule.postal_code_end,
                price=rule.price,
                price_label="R$ " + f"{rule.price:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                minimum_order=rule.minimum_order,
                minimum_order_label=(
                    "R$ " + f"{rule.minimum_order:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    if rule.minimum_order
                    else "Sem minimo"
                ),
                min_days=rule.min_delivery_days,
                max_days=rule.max_delivery_days,
                free_shipping=rule.free_shipping,
                pickup_available=rule.pickup_available,
                active=rule.is_active,
            )
        )
    company = db.session.get(Company, company_id)
    company_settings = dict(company.settings_json or {})
    delivery_settings = SimpleNamespace(
        pickup_enabled=bool(company_settings.get("pickup_enabled", False)),
        pickup_address=company_settings.get("pickup_address", ""),
    )
    return render_template(
        "delivery/index.html",
        rules=rule_views,
        delivery_rules=rule_views,
        delivery_settings=delivery_settings,
    )


@bp.post("")
@bp.post("/create")
@login_required
@roles_required("ADMIN", "OWNER")
def create():
    data = payload()
    if data.get("id"):
        try:
            return update(int(data["id"]))
        except (TypeError, ValueError):
            return failure("Regra invalida.", status=422)
    rule = DeliveryRule(company_id=current_company_id())
    try:
        _apply(rule, data)
        db.session.add(rule)
        db.session.flush()
        record_audit("delivery_rule.create", rule)
        db.session.commit()
    except (ValueError, IntegrityError) as exc:
        db.session.rollback()
        return failure(str(exc) if isinstance(exc, ValueError) else "Regra duplicada.", status=422)
    return success("Regra de entrega criada.", data=_data(rule), endpoint="delivery.index", status=201)


@bp.post("/<int:rule_id>")
@bp.put("/<int:rule_id>")
@bp.patch("/<int:rule_id>")
@login_required
@roles_required("ADMIN", "OWNER")
def update(rule_id: int):
    rule = tenant_get_or_404(DeliveryRule, rule_id)
    try:
        _apply(rule, payload())
        record_audit("delivery_rule.update", rule)
        db.session.commit()
    except (ValueError, IntegrityError) as exc:
        db.session.rollback()
        return failure(str(exc) if isinstance(exc, ValueError) else "Dados conflitantes.", status=422)
    return success("Regra atualizada.", data=_data(rule), endpoint="delivery.index")


@bp.delete("/<int:rule_id>")
@bp.post("/<int:rule_id>/archive")
@bp.post("/<int:rule_id>/delete")
@login_required
@roles_required("ADMIN", "OWNER")
def delete(rule_id: int):
    rule = tenant_get_or_404(DeliveryRule, rule_id)
    rule.is_active = False
    record_audit("delivery_rule.archive", rule)
    db.session.commit()
    return success("Regra arquivada.", endpoint="delivery.index")


@bp.post("/<int:rule_id>/toggle")
@login_required
@roles_required("ADMIN", "OWNER")
def toggle(rule_id: int):
    rule = tenant_get_or_404(DeliveryRule, rule_id)
    rule.is_active = not rule.is_active
    record_audit("delivery_rule.toggle", rule, {"is_active": rule.is_active})
    db.session.commit()
    return success("Status da regra atualizado.", data={"id": rule.id, "active": rule.is_active})


@bp.post("/pickup")
@login_required
@roles_required("ADMIN", "OWNER")
def pickup():
    company = db.session.get(Company, current_company_id())
    settings = dict(company.settings_json or {})
    data = payload()
    settings["pickup_enabled"] = coerce_bool(data.get("enabled"), False)
    if "address" in data:
        settings["pickup_address"] = str(data["address"]).strip()[:500]
    company.settings_json = settings
    db.session.commit()
    return success("Configuracao de retirada atualizada.")


@bp.route("/simulate", methods=["GET", "POST"])
@login_required
def simulate():
    data = request.args.to_dict() if request.method == "GET" else payload()
    try:
        options = DeliveryService.options(
            current_company_id(),
            city=data.get("city"),
            neighborhood=data.get("neighborhood"),
            postal_code=data.get("postal_code", data.get("zip_code")),
            order_total=data.get("order_total"),
        )
    except DomainError as exc:
        return jsonify(ok=False, message=exc.message), exc.status_code
    return jsonify(ok=True, options=options, found=bool(options))
