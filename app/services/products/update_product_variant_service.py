"""Use case for updating a product variant."""

from app.extensions import db
from app.models import ProductVariant
from app.services.tenancy import tenant_get


class UpdateProductVariantService:
    def execute(
        self,
        company_id: int,
        variant_id: int,
        *,
        commit: bool = True,
        **changes,
    ) -> ProductVariant:
        variant = tenant_get(ProductVariant, company_id, variant_id)
        for field, maximum in {"name": 180, "color": 80, "size": 80, "sku": 80}.items():
            if field in changes:
                value = changes[field]
                setattr(
                    variant,
                    field,
                    str(value).strip()[:maximum] or None if value is not None else None,
                )
        if "price" in changes:
            variant.price = changes["price"]
        if "is_active" in changes:
            variant.is_active = bool(changes["is_active"])
        db.session.commit() if commit else db.session.flush()
        return variant


__all__ = ["UpdateProductVariantService"]
