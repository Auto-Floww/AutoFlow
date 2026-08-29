"""Use case for listing tenant-scoped products."""

from sqlalchemy import or_

from app.models import Product


class ListProductsService:
    """Build the tenant-safe product query used by API and HTML adapters."""

    def execute(
        self,
        company_id: int,
        *,
        search: str = "",
        category: str = "",
        active: bool | None = None,
    ):
        query = Product.for_company(company_id)
        search = str(search).strip()
        category = str(category).strip()
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Product.name.ilike(pattern),
                    Product.sku.ilike(pattern),
                    Product.brand.ilike(pattern),
                )
            )
        if category:
            query = query.filter(Product.category == category)
        if active is not None:
            query = query.filter(Product.is_active.is_(bool(active)))
        return query.order_by(Product.updated_at.desc())


__all__ = ["ListProductsService"]
