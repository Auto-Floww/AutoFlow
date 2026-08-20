"""Clientes, historico e pipeline CRM."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from app.extensions import db, limiter
from app.models import Conversation, Customer, CustomerTag, Tag
from app.models.base import utcnow
from app.routes.helpers import company_local, failure, model_dict, payload, record_audit, success
from app.services.customer_service import CRM_STAGES, CustomerService
from app.services.exceptions import DomainError
from app.tenant import current_company_id, tenant_get_or_404


bp = Blueprint("customers", __name__, url_prefix="/customers")

STAGE_ORDER = ["NOVO", "INTERESSADO", "QUALIFICADO", "PROPOSTA", "VENDA", "PERDIDO"]
STAGE_TO_UI = {
    "NOVO": "NEW",
    "INTERESSADO": "INTERESTED",
    "QUALIFICADO": "QUALIFIED",
    "PROPOSTA": "PROPOSAL",
    "VENDA": "SALE",
    "PERDIDO": "LOST",
}
STAGE_FROM_UI = {value: key for key, value in STAGE_TO_UI.items()}


def _opportunity_value(value) -> Decimal | None:
    if value in {None, ""}:
        return None
    raw = str(value).replace("R$", "").replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Valor da oportunidade invalido") from exc
    if amount < 0:
        raise ValueError("Valor da oportunidade invalido")
    return amount


def _money_label(value) -> str:
    if value is None:
        return "Não informado"
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _customer_view(customer: Customer):
    local_interaction = company_local(
        customer.last_interaction_at,
        getattr(customer.company, "timezone", "UTC") or "UTC",
    )
    return SimpleNamespace(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        email=customer.email,
        company=customer.organization,
        organization=customer.organization,
        notes=customer.notes,
        stage=STAGE_TO_UI.get(customer.crm_stage, customer.crm_stage),
        crm_stage=customer.crm_stage,
        opportunity_title=customer.opportunity_title,
        opportunity_value=customer.opportunity_value,
        opportunity_value_label=_money_label(customer.opportunity_value),
        next_action=customer.next_action,
        next_action_label=customer.next_action,
        active=customer.status == "ACTIVE",
        status=customer.status,
        tags=[link.tag for link in customer.tag_links if link.tag and link.tag.is_active],
        last_interaction_label=(
            local_interaction.strftime("%d/%m/%Y %H:%M")
            if local_interaction
            else "Sem interacao"
        ),
        conversations_count=customer.conversations.count(),
        last_interaction_at=customer.last_interaction_at,
    )


def _customer_data(customer: Customer) -> dict:
    return {
        **model_dict(
            customer,
            "id",
            "name",
            "phone",
            "email",
            "organization",
            "notes",
            "status",
            "crm_stage",
            "opportunity_title",
            "opportunity_value",
            "next_action",
            "last_interaction_at",
            "created_at",
        ),
        "tags": [
            {"id": link.tag.id, "name": link.tag.name, "color": link.tag.color}
            for link in customer.tag_links
            if link.tag and link.tag.is_active
        ],
    }


@bp.get("")
@login_required
def index():
    company_id = current_company_id()
    search = request.args.get("q", "").strip()
    stage = request.args.get("stage", "").upper()
    status = request.args.get("status", "").upper()
    page = max(1, request.args.get("page", 1, type=int))
    query = CustomerService.list(company_id, search=search, stage=stage, status=status)
    pagination = query.paginate(page=page, per_page=25, error_out=False)
    tags = Tag.for_company(company_id).filter(Tag.is_active.is_(True)).order_by(Tag.name).all()
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    customer_stats = SimpleNamespace(
        total=Customer.for_company(company_id).count(),
        new_this_month=Customer.for_company(company_id).filter(Customer.created_at >= month_start).count(),
        opportunities=Customer.for_company(company_id).filter(Customer.crm_stage.in_(("QUALIFICADO", "PROPOSTA"))).count(),
        active_recently=Customer.for_company(company_id).filter(Customer.last_interaction_at >= now - timedelta(days=30)).count(),
    )
    return render_template(
        "customers/index.html",
        customers=[_customer_view(item) for item in pagination.items],
        pagination=pagination,
        customer_pagination=pagination,
        customer_stats=customer_stats,
        tags=tags,
        stages=STAGE_ORDER,
        filters={"q": search, "stage": stage, "status": status},
    )


@bp.post("")
@bp.post("/create")
@login_required
@limiter.limit("30 per minute")
def create():
    data = payload()
    if data.get("id"):
        try:
            return update(int(data["id"]))
        except (TypeError, ValueError):
            return failure("Cliente invalido.", status=422)
    if data.get("customer_id"):
        try:
            customer_id = int(data["customer_id"])
            stage = STAGE_FROM_UI.get(str(data.get("stage", "NEW")).upper(), str(data.get("stage", "NOVO")).upper())
            changes = {
                "crm_stage": stage,
                "opportunity_title": str(data.get("opportunity_title", "")).strip()[:180] or None,
                "opportunity_value": _opportunity_value(data.get("opportunity_value")),
                "next_action": str(data.get("next_action", "")).strip()[:255] or None,
            }
            customer = CustomerService.update(
                current_company_id(), customer_id, **changes
            )
            record_audit("customer.crm_stage", customer, changes)
            db.session.commit()
            return success("Oportunidade adicionada ao CRM.", endpoint="customers.crm")
        except (DomainError, TypeError, ValueError) as exc:
            message = exc.message if isinstance(exc, DomainError) else "Oportunidade invalida."
            return failure(message, status=422)
    try:
        customer = CustomerService.create(
            current_company_id(),
            name=str(data.get("name", "")),
            phone=str(data.get("phone", "")),
            email=data.get("email"),
            organization=data.get("organization", data.get("company")),
            notes=data.get("notes"),
        )
    except DomainError as exc:
        return failure(exc.message, errors=exc.details, status=exc.status_code)
    record_audit("customer.create", customer)
    db.session.commit()
    return success("Cliente cadastrado.", data=_customer_data(customer), endpoint="customers.index", status=201)


@bp.get("/<int:customer_id>")
@login_required
def detail(customer_id: int):
    customer = tenant_get_or_404(Customer, customer_id)
    conversations = (
        Conversation.for_company(current_company_id())
        .filter(Conversation.customer_id == customer.id)
        .order_by(Conversation.last_message_at.desc())
        .all()
    )
    if request.accept_mimetypes.best == "application/json":
        return jsonify(
            customer=_customer_data(customer),
            conversations=[
                model_dict(item, "id", "status", "ai_status", "last_message_at", "summary")
                for item in conversations
            ],
        )
    return render_template(
        "customers/detail.html", customer=customer, conversations=conversations
    )


@bp.post("/<int:customer_id>")
@bp.put("/<int:customer_id>")
@bp.patch("/<int:customer_id>")
@login_required
def update(customer_id: int):
    data = payload()
    allowed = {
        key: data[key]
        for key in (
            "name",
            "phone",
            "email",
            "organization",
            "notes",
            "status",
            "crm_stage",
            "opportunity_title",
            "opportunity_value",
            "next_action",
        )
        if key in data
    }
    if "stage" in data and "crm_stage" not in allowed:
        allowed["crm_stage"] = STAGE_FROM_UI.get(str(data["stage"]).upper(), str(data["stage"]).upper())
    if "company" in data and "organization" not in allowed:
        allowed["organization"] = data["company"]
    if "opportunity_value" in allowed:
        try:
            allowed["opportunity_value"] = _opportunity_value(
                allowed["opportunity_value"]
            )
        except ValueError as exc:
            return failure(str(exc), status=422)
    try:
        customer = CustomerService.update(current_company_id(), customer_id, **allowed)
    except DomainError as exc:
        return failure(exc.message, errors=exc.details, status=exc.status_code)
    record_audit("customer.update", customer, {key: "updated" for key in allowed})
    db.session.commit()
    return success("Cliente atualizado.", data=_customer_data(customer), endpoint="customers.index")


@bp.delete("/<int:customer_id>")
@bp.post("/<int:customer_id>/archive")
@bp.post("/<int:customer_id>/delete")
@login_required
def archive(customer_id: int):
    customer = tenant_get_or_404(Customer, customer_id)
    customer.status = "INACTIVE"
    record_audit("customer.archive", customer, {"status": "INACTIVE"})
    db.session.commit()
    return success("Cliente arquivado.", endpoint="customers.index")


@bp.get("/crm")
@bp.get("/pipeline")
@login_required
def crm():
    company_id = current_company_id()
    customers = CustomerService.list(company_id).limit(500).all()
    pipeline = {value: [] for value in STAGE_TO_UI.values()}
    for customer in customers:
        pipeline.setdefault(STAGE_TO_UI.get(customer.crm_stage, customer.crm_stage), []).append(_customer_view(customer))
    sale_count = len(pipeline.get("SALE", []))
    total_count = len(customers)
    total_value = sum(
        (item.opportunity_value or Decimal("0"))
        for item in customers
        if item.crm_stage != "PERDIDO"
    )
    won_values = [
        item.opportunity_value
        for item in customers
        if item.crm_stage == "VENDA" and item.opportunity_value is not None
    ]
    crm_stats = SimpleNamespace(
        total_value_label=_money_label(total_value),
        total_count=total_count,
        conversion_rate=round(sale_count * 100 / total_count) if total_count else 0,
        average_ticket_label=_money_label(
            sum(won_values, Decimal("0")) / len(won_values)
            if won_values
            else Decimal("0")
        ),
    )
    return render_template(
        "customers/crm.html",
        pipeline=pipeline,
        stages=STAGE_ORDER,
        customers=customers,
        available_customers=customers,
        crm_stats=crm_stats,
    )


@bp.post("/<int:customer_id>/stage")
@login_required
@limiter.limit("120 per minute")
def update_stage(customer_id: int):
    stage = str(payload().get("stage", "")).upper()
    stage = STAGE_FROM_UI.get(stage, stage)
    if stage not in CRM_STAGES:
        return failure("Estagio de CRM invalido.", status=422)
    try:
        customer = CustomerService.update(
            current_company_id(), customer_id, crm_stage=stage
        )
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    record_audit("customer.crm_stage", customer, {"crm_stage": stage})
    db.session.commit()
    return success("Etapa atualizada.", data={"id": customer.id, "stage": stage})


@bp.post("/<int:customer_id>/tags")
@login_required
def add_tag(customer_id: int):
    data = payload()
    try:
        tag = CustomerService.add_tag(
            current_company_id(),
            customer_id,
            tag_id=int(data["tag_id"]) if data.get("tag_id") else None,
            tag_name=data.get("tag_name"),
            color=str(data.get("color", "#14b8a6")),
        )
    except (DomainError, ValueError) as exc:
        message = exc.message if isinstance(exc, DomainError) else "Tag invalida."
        status = exc.status_code if isinstance(exc, DomainError) else 422
        return failure(message, status=status)
    return success("Tag adicionada.", data=model_dict(tag, "id", "name", "color"))


@bp.delete("/<int:customer_id>/tags/<int:tag_id>")
@login_required
def remove_tag(customer_id: int, tag_id: int):
    company_id = current_company_id()
    tenant_get_or_404(Customer, customer_id)
    link = CustomerTag.for_company(company_id).filter_by(
        customer_id=customer_id, tag_id=tag_id
    ).first_or_404()
    db.session.delete(link)
    db.session.commit()
    return success("Tag removida.")


@bp.patch("/<int:customer_id>/note")
@bp.post("/<int:customer_id>/note")
@login_required
def save_note(customer_id: int):
    note = str(payload().get("note", payload().get("notes", ""))).strip()
    if len(note) > 4000:
        return failure("A observacao deve ter ate 4000 caracteres.", status=422)
    try:
        customer = CustomerService.update(
            current_company_id(), customer_id, notes=note
        )
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    record_audit("customer.note", customer, {"notes": "updated"})
    db.session.commit()
    return success("Observacao salva.", data={"id": customer.id})
