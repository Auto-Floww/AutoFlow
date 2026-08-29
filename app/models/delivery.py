"""Tenant delivery and pickup rules."""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, TimestampMixin


class DeliveryRule(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "delivery_rules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, default="Entrega")
    city = db.Column(db.String(120), index=True)
    neighborhood = db.Column(db.String(120), index=True)
    postal_code_start = db.Column(db.String(8), index=True)
    postal_code_end = db.Column(db.String(8), index=True)
    price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    free_shipping = db.Column(db.Boolean, nullable=False, default=False)
    minimum_order = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    min_delivery_days = db.Column(db.Integer, nullable=False, default=0)
    max_delivery_days = db.Column(db.Integer, nullable=False, default=0)
    pickup_available = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    priority = db.Column(db.Integer, nullable=False, default=100)

    __table_args__ = (
        db.CheckConstraint("price >= 0", name="ck_delivery_price"),
        db.CheckConstraint("minimum_order >= 0", name="ck_delivery_minimum"),
        db.CheckConstraint(
            "min_delivery_days >= 0 AND max_delivery_days >= min_delivery_days",
            name="ck_delivery_days",
        ),
        db.Index(
            "ix_delivery_company_location",
            "company_id",
            "city",
            "neighborhood",
            "is_active",
        ),
    )

    @property
    def active(self) -> bool:
        return self.is_active
