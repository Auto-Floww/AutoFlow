"""Use case for archiving a product without deleting its history."""

from app.extensions import db
from app.models import Product
from app.services.tenancy import tenant_get


class ArchiveProductService:
    def execute(
        self, company_id: int, product_id: int, *, commit: bool = True
    ) -> Product:
        product = tenant_get(Product, company_id, product_id)
        product.is_active = False
        for variant in product.variants:
            variant.is_active = False
        db.session.commit() if commit else db.session.flush()
        return product


__all__ = ["ArchiveProductService"]
