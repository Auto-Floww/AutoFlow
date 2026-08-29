"""Use case for archiving a product variant."""

from app.extensions import db
from app.models import ProductVariant
from app.services.tenancy import tenant_get


class ArchiveProductVariantService:
    def execute(
        self, company_id: int, variant_id: int, *, commit: bool = True
    ) -> ProductVariant:
        variant = tenant_get(ProductVariant, company_id, variant_id)
        variant.is_active = False
        db.session.commit() if commit else db.session.flush()
        return variant


__all__ = ["ArchiveProductVariantService"]
