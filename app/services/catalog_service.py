"""Read-only product catalog service used by routes and AI tools."""

from __future__ import annotations

from app.extensions import db
from app.models import Product, ProductVariant
from app.services.exceptions import NotFoundError, ValidationError


class CatalogQueries:
    @staticmethod
    def search(
        company_id: int,
        *,
        query_text: str | None = None,
        category: str | None = None,
        active_only: bool = True,
        limit: int = 20,
    ) -> list[Product]:
        query = Product.for_company(company_id)
        if active_only:
            query = query.filter(Product.is_active.is_(True))
        if query_text:
            term = f"%{query_text.strip()[:120]}%"
            query = query.filter(
                db.or_(
                    Product.name.ilike(term),
                    Product.description.ilike(term),
                    Product.sku.ilike(term),
                    Product.brand.ilike(term),
                    Product.category.ilike(term),
                )
            )
        if category:
            query = query.filter(db.func.lower(Product.category) == category.strip().lower())
        return query.order_by(Product.name).limit(min(max(int(limit), 1), 50)).all()

    @staticmethod
    def get(
        company_id: int,
        *,
        product_id: int | None = None,
        sku: str | None = None,
    ) -> Product:
        if not product_id and not sku:
            raise ValidationError("product_id or sku is required")
        query = Product.for_company(company_id)
        if product_id:
            query = query.filter(Product.id == int(product_id))
        else:
            variant = ProductVariant.query.filter_by(
                company_id=int(company_id), sku=sku
            ).one_or_none()
            if variant:
                return variant.product
            query = query.filter(Product.sku == sku)
        product = query.one_or_none()
        if product is None:
            raise NotFoundError("Product not found")
        return product

    @staticmethod
    def serialize(product: Product, *, include_inventory: bool = True) -> dict:
        result = {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "sku": product.sku,
            "category": product.category,
            "brand": product.brand,
            "price": str(product.price),
            "promotional_price": (
                str(product.promotional_price)
                if product.promotional_price is not None
                else None
            ),
            "active": product.is_active,
            "variants": [],
        }
        for variant in product.variants:
            item = {
                "id": variant.id,
                "name": variant.name,
                "sku": variant.sku,
                "color": variant.color,
                "size": variant.size,
                "price": str(variant.effective_price),
                "active": variant.is_active,
            }
            if include_inventory:
                inventory = variant.inventory
                item["available_quantity"] = (
                    inventory.available_quantity if inventory else 0
                )
            result["variants"].append(item)
        if include_inventory and product.inventory:
            result["available_quantity"] = product.inventory.available_quantity
        return result


# Backwards-compatible alias; use-case Services live in ``app.services.catalog``.
CatalogService = CatalogQueries
