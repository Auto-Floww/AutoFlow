"""Catalog products and variants."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import synonym

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, TimestampMixin


class Product(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    sku = db.Column(db.String(80))
    category = db.Column(db.String(100), index=True)
    brand = db.Column(db.String(100))
    price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    promotional_price = db.Column(db.Numeric(12, 2))
    image_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    attributes_json = db.Column("attributes", db.JSON, nullable=False, default=dict)

    active = synonym("is_active")

    variants = db.relationship(
        "ProductVariant",
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    inventory = db.relationship(
        "Inventory",
        primaryjoin="and_(Product.id == foreign(Inventory.product_id), Inventory.variant_id == None)",
        uselist=False,
        viewonly=True,
    )

    __table_args__ = (
        db.UniqueConstraint("company_id", "sku", name="uq_product_company_sku"),
        db.CheckConstraint("price >= 0", name="ck_products_price"),
        db.CheckConstraint(
            "promotional_price IS NULL OR promotional_price >= 0",
            name="ck_products_promotional_price",
        ),
        db.Index("ix_product_company_name", "company_id", "name"),
        db.Index("ix_product_company_category", "company_id", "category"),
    )

    @property
    def effective_price(self):
        return self.promotional_price if self.promotional_price is not None else self.price


class ProductVariant(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "product_variants"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(180))
    color = db.Column(db.String(80), index=True)
    size = db.Column(db.String(80), index=True)
    sku = db.Column(db.String(80))
    price = db.Column(db.Numeric(12, 2))
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    attributes_json = db.Column("attributes", db.JSON, nullable=False, default=dict)

    active = synonym("is_active")

    product = db.relationship("Product", back_populates="variants")
    inventory = db.relationship(
        "Inventory",
        back_populates="variant",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        db.UniqueConstraint("company_id", "sku", name="uq_variant_company_sku"),
        db.CheckConstraint("price IS NULL OR price >= 0", name="ck_variants_price"),
        db.Index("ix_variant_product_options", "product_id", "color", "size"),
    )

    @property
    def effective_price(self):
        return self.price if self.price is not None else self.product.effective_price
