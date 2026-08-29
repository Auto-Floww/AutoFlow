"""Use case for updating a tenant-scoped product."""

from app.extensions import db
from app.models import Product
from app.services.tenancy import tenant_get


class UpdateProductService:
    _TEXT_FIELDS = {
        "name": 180,
        "description": 6000,
        "sku": 80,
        "category": 100,
        "brand": 100,
        "image_url": 500,
    }

    def execute(
        self,
        company_id: int,
        product_id: int,
        *,
        commit: bool = True,
        **changes,
    ) -> Product:
        product = tenant_get(Product, company_id, product_id)
        for field, maximum in self._TEXT_FIELDS.items():
            if field in changes:
                value = changes[field]
                setattr(
                    product,
                    field,
                    str(value).strip()[:maximum] or None if value is not None else None,
                )
        if not product.name:
            raise ValueError("Informe o nome do produto")
        for field in ("price", "promotional_price"):
            if field in changes:
                setattr(product, field, changes[field])
        if "is_active" in changes:
            product.is_active = bool(changes["is_active"])
        db.session.commit() if commit else db.session.flush()
        return product


__all__ = ["UpdateProductService"]
