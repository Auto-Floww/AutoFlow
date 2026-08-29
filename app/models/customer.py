"""Customer and lightweight CRM model."""

from __future__ import annotations

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, TimestampMixin


class Customer(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(32), nullable=False)
    phone_normalized = db.Column(db.String(24), nullable=False)
    email = db.Column(db.String(255))
    organization = db.Column(db.String(160))
    notes = db.Column(db.Text)
    status = db.Column(db.String(24), nullable=False, default="ACTIVE", index=True)
    crm_stage = db.Column(db.String(24), nullable=False, default="NOVO", index=True)
    opportunity_title = db.Column(db.String(180))
    opportunity_value = db.Column(db.Numeric(14, 2))
    next_action = db.Column(db.String(255))
    source = db.Column(db.String(40), nullable=False, default="WHATSAPP")
    preferences_json = db.Column("preferences", db.JSON, nullable=False, default=dict)
    last_interaction_at = db.Column(db.DateTime, index=True)

    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "phone_normalized", name="uq_customer_company_phone"
        ),
        db.CheckConstraint(
            "crm_stage IN ('NOVO','INTERESSADO','QUALIFICADO','PROPOSTA','VENDA','PERDIDO')",
            name="ck_customers_crm_stage",
        ),
        db.CheckConstraint(
            "status IN ('ACTIVE','INACTIVE','BLOCKED')", name="ck_customers_status"
        ),
        db.CheckConstraint(
            "opportunity_value IS NULL OR opportunity_value >= 0",
            name="ck_customers_opportunity_value",
        ),
        db.Index("ix_customer_company_stage", "company_id", "crm_stage"),
        db.Index("ix_customer_company_name", "company_id", "name"),
    )

    conversations = db.relationship(
        "Conversation",
        back_populates="customer",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="dynamic",
    )
    appointments = db.relationship(
        "Appointment", back_populates="customer", lazy="dynamic"
    )
    tag_links = db.relationship(
        "CustomerTag",
        back_populates="customer",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    @property
    def company_name(self) -> str | None:
        return self.organization

    @company_name.setter
    def company_name(self, value: str | None) -> None:
        self.organization = value
