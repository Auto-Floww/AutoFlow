"""The only database capabilities exposed to the AI model."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal

from pydantic import Field

from app.extensions import db
from app.models import BusinessHour, Company, Conversation, Customer, ProductVariant
from app.models.base import utcnow
from app.services.appointment_service import AppointmentService
from app.services.catalog_service import CatalogService
from app.services.conversation_service import ConversationService
from app.services.customer_service import CustomerService
from app.services.delivery_service import DeliveryService
from app.services.exceptions import NotFoundError, ValidationError
from app.services.inventory_service import InventoryService
from app.services.knowledge_service import KnowledgeService
from app.services.notification_service import NotificationService
from app.services.tool_registry import ToolContext, ToolInput, ToolRegistry, ToolSpec


class SearchProductsInput(ToolInput):
    query: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=8, ge=1, le=20)


class GetProductInput(ToolInput):
    product_id: int | None = Field(default=None, ge=1)
    sku: str | None = Field(default=None, max_length=80)


class CheckInventoryInput(ToolInput):
    product_id: int | None = Field(default=None, ge=1)
    variant_id: int | None = Field(default=None, ge=1)
    sku: str | None = Field(default=None, max_length=80)
    color: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=80)


class DeliveryOptionsInput(ToolInput):
    city: str | None = Field(default=None, max_length=120)
    neighborhood: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=16)
    order_total: str | None = Field(default=None, max_length=32)


class BusinessHoursInput(ToolInput):
    professional_id: int | None = Field(default=None, ge=1)
    weekday: int | None = Field(default=None, ge=0, le=6)


class SearchKnowledgeInput(ToolInput):
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


class AvailableAppointmentsInput(ToolInput):
    service_id: int = Field(ge=1)
    date: str = Field(description="Local date in YYYY-MM-DD format")
    professional_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=12, ge=1, le=30)


class CreateAppointmentInput(ToolInput):
    service_id: int = Field(ge=1)
    professional_id: int = Field(ge=1)
    starts_at: str = Field(description="ISO 8601 date/time, including offset when known")
    customer_id: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=1000)


class CancelAppointmentInput(ToolInput):
    appointment_id: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=255)


class GetCustomerInput(ToolInput):
    customer_id: int | None = Field(default=None, ge=1)
    phone: str | None = Field(default=None, max_length=32)


class UpdateCustomerInput(ToolInput):
    customer_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    organization: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)
    crm_stage: Literal[
        "NOVO", "INTERESSADO", "QUALIFICADO", "PROPOSTA", "VENDA", "PERDIDO"
    ] | None = None


class AddCustomerTagInput(ToolInput):
    tag_name: str = Field(min_length=1, max_length=80)
    customer_id: int | None = Field(default=None, ge=1)


class TransferToHumanInput(ToolInput):
    reason: str | None = Field(default=None, max_length=500)


def _customer_dict(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "organization": customer.organization,
        "crm_stage": customer.crm_stage,
        "status": customer.status,
        "preferences": customer.preferences_json or {},
    }


def _record_product_consultations(context: ToolContext, products: list[dict]) -> None:
    """Registra somente produtos realmente retornados pelas tools."""

    if not context.conversation_id or not products:
        return
    conversation = (
        Conversation.for_company(context.company_id)
        .filter(Conversation.id == context.conversation_id)
        .with_for_update()
        .one_or_none()
    )
    if conversation is None:
        return
    memory = dict(conversation.memory_json or {})
    events = list(memory.get("products_consulted") or [])[-199:]
    seen: set[tuple[int | None, str]] = set()
    for product in products:
        product_id = product.get("id") or product.get("product_id")
        name = str(product.get("name") or "").strip()
        identity = (int(product_id) if product_id else None, name)
        if not name or identity in seen:
            continue
        seen.add(identity)
        events.append(
            {
                "id": identity[0],
                "name": name[:180],
                "consulted_at": utcnow().isoformat(),
            }
        )
    memory["products_consulted"] = events[-200:]
    conversation.memory_json = memory
    db.session.commit()


def _search_products(context: ToolContext, query=None, category=None, limit=8):
    rows = CatalogService.search(
        context.company_id, query_text=query, category=category, limit=limit
    )
    result = [CatalogService.serialize(product) for product in rows]
    _record_product_consultations(context, result)
    return result


def _get_product(context: ToolContext, product_id=None, sku=None):
    result = CatalogService.serialize(
        CatalogService.get(context.company_id, product_id=product_id, sku=sku)
    )
    _record_product_consultations(context, [result])
    return result


def _check_inventory(
    context: ToolContext,
    product_id=None,
    variant_id=None,
    sku=None,
    color=None,
    size=None,
):
    if not any((product_id, variant_id, sku)):
        raise ValidationError("product_id, variant_id, or sku is required")
    rows = InventoryService.find_for_catalog(
        context.company_id,
        product_id=product_id,
        variant_id=variant_id,
        sku=sku,
        color=color,
        size=size,
    )
    result = [
        {
            "inventory_id": inventory.id,
            "product_id": inventory.product_id
            or (inventory.variant.product_id if inventory.variant else None),
            "variant_id": inventory.variant_id,
            "sku": (
                inventory.variant.sku
                if inventory.variant
                else (inventory.product.sku if inventory.product else None)
            ),
            "color": inventory.variant.color if inventory.variant else None,
            "size": inventory.variant.size if inventory.variant else None,
            "available_quantity": inventory.available_quantity,
            "in_stock": inventory.available_quantity > 0,
            "name": (
                inventory.variant.product.name
                if inventory.variant
                else (inventory.product.name if inventory.product else "")
            ),
        }
        for inventory in rows
    ]
    _record_product_consultations(context, result)
    return result


def _delivery_options(context: ToolContext, **arguments):
    return DeliveryService.options(context.company_id, **arguments)


def _business_hours(context: ToolContext, professional_id=None, weekday=None):
    company = Company.query.filter_by(id=context.company_id).one()
    query = BusinessHour.for_company(context.company_id)
    if professional_id:
        query = query.filter(
            db.or_(
                BusinessHour.professional_id == professional_id,
                BusinessHour.professional_id.is_(None),
            )
        )
    if weekday is not None:
        query = query.filter(BusinessHour.weekday == weekday)
    return {
        "timezone": company.timezone,
        "hours": [
            {
                "weekday": row.weekday,
                "professional_id": row.professional_id,
                "closed": row.is_closed,
                "opens_at": row.opens_at.isoformat() if row.opens_at else None,
                "closes_at": row.closes_at.isoformat() if row.closes_at else None,
            }
            for row in query.order_by(BusinessHour.weekday).all()
        ],
    }


def _search_faq(context: ToolContext, query, limit=5):
    return KnowledgeService.search_faq(context.company_id, query, limit=limit)


def _search_knowledge(context: ToolContext, query, limit=5):
    return KnowledgeService.search_knowledge(context.company_id, query, limit=limit)


def _available_appointments(
    context: ToolContext, service_id, date, professional_id=None, limit=12
):
    return AppointmentService.available_slots(
        context.company_id,
        service_id=service_id,
        day=date,
        professional_id=professional_id,
        limit=limit,
    )


def _create_appointment(
    context: ToolContext,
    service_id,
    professional_id,
    starts_at,
    customer_id=None,
    notes=None,
):
    tenant_customer_id = context.customer_id
    if not tenant_customer_id:
        raise ValidationError("No customer is associated with this conversation")
    if customer_id and customer_id != context.customer_id:
        raise ValidationError("The AI may only book for the current customer")
    material = (
        f"{context.company_id}:{context.conversation_id}:{tenant_customer_id}:"
        f"{service_id}:{professional_id}:{starts_at}"
    )
    idempotency_key = "ai:" + hashlib.sha256(material.encode()).hexdigest()
    appointment = AppointmentService.create(
        context.company_id,
        customer_id=tenant_customer_id,
        service_id=service_id,
        professional_id=professional_id,
        starts_at=starts_at,
        notes=notes,
        idempotency_key=idempotency_key,
    )
    NotificationService.create(
        context.company_id,
        notification_type="NEW_APPOINTMENT",
        title="Novo agendamento",
        body=(
            f"{appointment.customer.name} agendou {appointment.service.name}."
        ),
        link_url="/appointments",
        data={"appointment_id": appointment.id},
        idempotency_key=f"appointment:{appointment.id}:created",
    )
    return {
        "appointment_id": appointment.id,
        "status": appointment.status,
        "starts_at": appointment.starts_at.isoformat(),
        "ends_at": appointment.ends_at.isoformat(),
        "confirmed": appointment.status == "CONFIRMED",
    }


def _cancel_appointment(context: ToolContext, appointment_id, reason=None):
    if not context.customer_id:
        raise ValidationError("No customer is associated with this conversation")
    existing = AppointmentService.get(context.company_id, appointment_id)
    if existing.customer_id != context.customer_id:
        raise NotFoundError("Appointment not found")
    appointment = AppointmentService.cancel(
        context.company_id, appointment_id, reason=reason
    )
    NotificationService.create(
        context.company_id,
        notification_type="APPOINTMENT_CANCELLED",
        title="Agendamento cancelado",
        body=f"{appointment.customer.name} — {appointment.service.name}",
        link_url="/appointments",
        data={"appointment_id": appointment.id},
        idempotency_key=f"appointment:{appointment.id}:cancelled",
    )
    return {"appointment_id": appointment.id, "status": appointment.status}


def _get_customer(context: ToolContext, customer_id=None, phone=None):
    if not context.customer_id:
        raise ValidationError("No customer is associated with this conversation")
    if customer_id and customer_id != context.customer_id:
        raise ValidationError("The AI may only access the current customer")
    customer = CustomerService.get(context.company_id, context.customer_id)
    if phone and CustomerService.find_by_phone(context.company_id, phone) != customer:
        raise NotFoundError("Customer not found")
    return _customer_dict(customer)


def _update_customer(context: ToolContext, customer_id=None, **changes):
    target = context.customer_id
    if not target:
        raise ValidationError("No customer is associated with this conversation")
    if customer_id and customer_id != context.customer_id:
        raise ValidationError("The AI may only update the current customer")
    customer = CustomerService.update(context.company_id, target, **changes)
    return _customer_dict(customer)


def _add_customer_tag(context: ToolContext, tag_name, customer_id=None):
    target = context.customer_id
    if not target:
        raise ValidationError("No customer is associated with this conversation")
    if customer_id and customer_id != context.customer_id:
        raise ValidationError("The AI may only tag the current customer")
    tag = CustomerService.add_tag(
        context.company_id, target, tag_name=tag_name
    )
    return {"customer_id": target, "tag_id": tag.id, "tag_name": tag.name}


def _transfer_to_human(context: ToolContext, reason=None):
    if not context.conversation_id:
        raise ValidationError("No conversation is associated with this request")
    conversation = ConversationService.transfer_to_human(
        context.company_id, context.conversation_id, reason=reason
    )
    return {
        "conversation_id": conversation.id,
        "transferred": True,
        "ai_status": conversation.ai_status,
    }


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    specifications = [
        ToolSpec(
            "search_products",
            "Search the company's real product catalog. Use before describing available products.",
            SearchProductsInput,
            _search_products,
        ),
        ToolSpec(
            "get_product",
            "Get authoritative details and prices for one product.",
            GetProductInput,
            _get_product,
        ),
        ToolSpec(
            "check_inventory",
            "Check real-time stock for a product or variant. Required before claiming availability.",
            CheckInventoryInput,
            _check_inventory,
        ),
        ToolSpec(
            "get_delivery_options",
            "Get configured delivery prices, deadlines, minimums, and pickup options.",
            DeliveryOptionsInput,
            _delivery_options,
        ),
        ToolSpec(
            "get_business_hours",
            "Get the company's configured business hours in its local timezone.",
            BusinessHoursInput,
            _business_hours,
        ),
        ToolSpec(
            "search_faq", "Search answers approved in the company FAQ.", SearchKnowledgeInput, _search_faq
        ),
        ToolSpec(
            "search_knowledge",
            "Search approved company knowledge documents.",
            SearchKnowledgeInput,
            _search_knowledge,
        ),
        ToolSpec(
            "get_available_appointments",
            "Get current bookable appointment slots. Required before offering a time.",
            AvailableAppointmentsInput,
            _available_appointments,
        ),
        ToolSpec(
            "create_appointment",
            "Create and confirm an appointment transactionally after the customer chooses a slot.",
            CreateAppointmentInput,
            _create_appointment,
        ),
        ToolSpec(
            "cancel_appointment",
            "Cancel an existing appointment owned by this company.",
            CancelAppointmentInput,
            _cancel_appointment,
        ),
        ToolSpec(
            "get_customer", "Get the current customer's saved profile.", GetCustomerInput, _get_customer
        ),
        ToolSpec(
            "update_customer",
            "Update explicitly provided fields on the current customer's profile.",
            UpdateCustomerInput,
            _update_customer,
        ),
        ToolSpec(
            "add_customer_tag",
            "Attach a company-scoped tag to the current customer.",
            AddCustomerTagInput,
            _add_customer_tag,
        ),
        ToolSpec(
            "transfer_to_human",
            "Pause AI and request a human agent when requested or required.",
            TransferToHumanInput,
            _transfer_to_human,
        ),
    ]
    for specification in specifications:
        registry.register(specification)
    return registry
