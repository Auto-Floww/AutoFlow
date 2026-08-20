"""Inventory balance and immutable movement ledger."""

from __future__ import annotations

from app.extensions import db
from app.models.base import ReprMixin, TenantMixin, TimestampMixin


class Inventory(db.Model, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "inventories"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    variant_id = db.Column(
        db.Integer,
        db.ForeignKey("product_variants.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    quantity = db.Column(db.Integer, nullable=False, default=0)
    reserved_quantity = db.Column(db.Integer, nullable=False, default=0)
    minimum_quantity = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship("Product", foreign_keys=[product_id], overlaps="inventory")
    variant = db.relationship("ProductVariant", back_populates="inventory")
    movements = db.relationship(
        "InventoryMovement",
        back_populates="inventory",
        lazy="dynamic",
    )

    __table_args__ = (
        db.UniqueConstraint("company_id", "product_id", name="uq_inventory_product"),
        db.CheckConstraint(
            "(product_id IS NOT NULL AND variant_id IS NULL) OR "
            "(product_id IS NULL AND variant_id IS NOT NULL)",
            name="ck_inventory_catalog_item",
        ),
        db.CheckConstraint("quantity >= 0", name="ck_inventory_quantity"),
        db.CheckConstraint(
            "reserved_quantity >= 0 AND reserved_quantity <= quantity",
            name="ck_inventory_reserved",
        ),
        db.CheckConstraint("minimum_quantity >= 0", name="ck_inventory_minimum"),
        db.Index("ix_inventory_company_low", "company_id", "quantity", "minimum_quantity"),
    )

    @property
    def available_quantity(self) -> int:
        return self.quantity - self.reserved_quantity

    @property
    def is_low_stock(self) -> bool:
        return self.available_quantity <= self.minimum_quantity


class InventoryMovement(db.Model, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "inventory_movements"

    id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(
        db.Integer,
        db.ForeignKey("inventories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    movement_type = db.Column(db.String(16), nullable=False, index=True)
    quantity_delta = db.Column(db.Integer, nullable=False)
    quantity_before = db.Column(db.Integer, nullable=False)
    quantity_after = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255))
    reference_type = db.Column(db.String(64))
    reference_id = db.Column(db.String(100))
    idempotency_key = db.Column(db.String(190))
    metadata_json = db.Column("metadata", db.JSON, nullable=False, default=dict)

    inventory = db.relationship("Inventory", back_populates="movements")
    actor_user = db.relationship("User", foreign_keys=[actor_user_id])

    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "idempotency_key", name="uq_inventory_movement_idempotency"
        ),
        db.CheckConstraint(
            "movement_type IN ('IN','OUT','ADJUSTMENT','RESERVE','RELEASE')",
            name="ck_inventory_movement_type",
        ),
        db.CheckConstraint("quantity_delta <> 0", name="ck_inventory_movement_delta"),
        db.CheckConstraint(
            "quantity_before >= 0 AND quantity_after >= 0",
            name="ck_inventory_movement_balances",
        ),
        db.Index("ix_movement_inventory_created", "inventory_id", "created_at"),
    )
