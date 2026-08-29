"""Customer, CRM stage, and customer-tag operations."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Customer, CustomerTag, Tag
from app.models.base import utcnow
from app.services.exceptions import ConflictError, ValidationError
from app.services.tenancy import ensure_same_company, tenant_get


PHONE_RE = re.compile(r"\D+")
CRM_STAGES = {"NOVO", "INTERESSADO", "QUALIFICADO", "PROPOSTA", "VENDA", "PERDIDO"}


def normalize_phone(phone: str, default_country_code: str = "55") -> str:
    if not isinstance(phone, str) or not phone.strip():
        raise ValidationError("Phone is required")
    raw = phone.strip()
    digits = PHONE_RE.sub("", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if raw.startswith("+"):
        normalized = digits
    elif len(digits) in {10, 11} and default_country_code:
        normalized = f"{default_country_code}{digits}"
    else:
        normalized = digits
    if not 8 <= len(normalized) <= 15:
        raise ValidationError("Phone must be a valid international number")
    return normalized


class CustomerOperations:
    @staticmethod
    def get(company_id: int, customer_id: int) -> Customer:
        return tenant_get(Customer, company_id, customer_id)

    @staticmethod
    def find_by_phone(company_id: int, phone: str) -> Customer | None:
        normalized = normalize_phone(phone)
        return Customer.query.filter_by(
            company_id=int(company_id), phone_normalized=normalized
        ).one_or_none()

    @staticmethod
    def list(
        company_id: int,
        *,
        search: str | None = None,
        stage: str | None = None,
        status: str | None = None,
    ):
        query = Customer.for_company(company_id)
        if search:
            term = f"%{search.strip()[:100]}%"
            query = query.filter(
                db.or_(
                    Customer.name.ilike(term),
                    Customer.phone_normalized.ilike(term),
                    Customer.email.ilike(term),
                )
            )
        if stage:
            query = query.filter(Customer.crm_stage == stage.upper())
        if status:
            query = query.filter(Customer.status == status.upper())
        return query.order_by(Customer.last_interaction_at.desc(), Customer.created_at.desc())

    @staticmethod
    def create(
        company_id: int,
        *,
        name: str,
        phone: str,
        email: str | None = None,
        organization: str | None = None,
        notes: str | None = None,
        source: str = "MANUAL",
        commit: bool = True,
    ) -> Customer:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Customer name is required")
        normalized = normalize_phone(phone)
        customer = Customer(
            company_id=int(company_id),
            name=name[:160],
            phone=phone.strip()[:32],
            phone_normalized=normalized,
            email=(email or "").strip().lower()[:255] or None,
            organization=(organization or "").strip()[:160] or None,
            notes=notes,
            source=(source or "MANUAL").upper()[:40],
        )
        db.session.add(customer)
        try:
            db.session.flush()
            if commit:
                db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise ConflictError("A customer with this phone already exists") from exc
        return customer

    @staticmethod
    def upsert_from_whatsapp(
        company_id: int,
        *,
        phone: str,
        name: str | None = None,
        commit: bool = True,
    ) -> Customer:
        normalized = normalize_phone(phone)
        customer = Customer.query.filter_by(
            company_id=int(company_id), phone_normalized=normalized
        ).one_or_none()
        if customer is None:
            customer = Customer(
                company_id=int(company_id),
                name=(name or phone).strip()[:160],
                phone=phone.strip()[:32],
                phone_normalized=normalized,
                source="WHATSAPP",
            )
            db.session.add(customer)
        elif name and (not customer.name or customer.name == customer.phone):
            customer.name = name.strip()[:160]
        customer.last_interaction_at = utcnow()
        try:
            db.session.flush()
            if commit:
                db.session.commit()
        except IntegrityError:
            # A concurrent webhook may have inserted the same contact first.
            db.session.rollback()
            customer = Customer.query.filter_by(
                company_id=int(company_id), phone_normalized=normalized
            ).one()
        return customer

    @staticmethod
    def update(
        company_id: int,
        customer_id: int,
        *,
        commit: bool = True,
        **changes: Any,
    ) -> Customer:
        customer = tenant_get(Customer, company_id, customer_id, lock=True)
        previous_stage = customer.crm_stage
        allowed = {
            "name",
            "email",
            "organization",
            "notes",
            "status",
            "preferences_json",
            "opportunity_title",
            "opportunity_value",
            "next_action",
        }
        for key, value in changes.items():
            if key in allowed:
                setattr(customer, key, value.strip() if isinstance(value, str) else value)
        if customer.opportunity_title:
            customer.opportunity_title = customer.opportunity_title[:180]
        if customer.next_action:
            customer.next_action = customer.next_action[:255]
        if customer.opportunity_value is not None and customer.opportunity_value < 0:
            raise ValidationError("Opportunity value cannot be negative")
        if "phone" in changes:
            customer.phone = changes["phone"].strip()[:32]
            customer.phone_normalized = normalize_phone(changes["phone"])
        if "crm_stage" in changes:
            stage = str(changes["crm_stage"]).upper()
            if stage not in CRM_STAGES:
                raise ValidationError("Invalid CRM stage")
            customer.crm_stage = stage
        customer.last_interaction_at = utcnow()
        try:
            db.session.flush()
            if (
                customer.crm_stage in {"PROPOSTA", "VENDA"}
                and customer.crm_stage != previous_stage
            ):
                from app.services.notification_service import NotificationOperations

                title = (
                    "Oportunidade em proposta"
                    if customer.crm_stage == "PROPOSTA"
                    else "Venda registrada"
                )
                NotificationOperations.create(
                    company_id,
                    notification_type="IMPORTANT_OPPORTUNITY",
                    title=title,
                    body=f"{customer.name} avançou para {customer.crm_stage.title()}.",
                    link_url=f"/customers/{customer.id}",
                    data={"customer_id": customer.id, "stage": customer.crm_stage},
                    idempotency_key=(
                        f"important-opportunity:{customer.id}:{customer.crm_stage}:"
                        f"{utcnow().isoformat(timespec='microseconds')}"
                    ),
                    commit=False,
                )
            if commit:
                db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise ConflictError("Customer update conflicts with an existing record") from exc
        return customer

    @staticmethod
    def add_tag(
        company_id: int,
        customer_id: int,
        *,
        tag_id: int | None = None,
        tag_name: str | None = None,
        color: str = "#6D5DFB",
        commit: bool = True,
    ) -> Tag:
        customer = tenant_get(Customer, company_id, customer_id)
        if tag_id:
            tag = tenant_get(Tag, company_id, tag_id)
        else:
            name = (tag_name or "").strip()
            if not name:
                raise ValidationError("tag_id or tag_name is required")
            tag = Tag.query.filter_by(
                company_id=int(company_id), name=name[:80], tag_type="CUSTOMER"
            ).one_or_none()
            if tag is None:
                tag = Tag(
                    company_id=int(company_id),
                    name=name[:80],
                    color=color[:16],
                    tag_type="CUSTOMER",
                )
                db.session.add(tag)
                db.session.flush()
        ensure_same_company(company_id, customer, tag)
        link = CustomerTag.query.filter_by(
            company_id=int(company_id), customer_id=customer.id, tag_id=tag.id
        ).one_or_none()
        if link is None:
            db.session.add(
                CustomerTag(company_id=int(company_id), customer_id=customer.id, tag_id=tag.id)
            )
        if commit:
            db.session.commit()
        return tag


# Backwards-compatible alias; use-case Services live in ``app.services.customers``.
CustomerService = CustomerOperations
get_customer = CustomerOperations.get
update_customer = CustomerOperations.update
