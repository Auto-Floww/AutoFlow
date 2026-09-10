"""Caso de uso para buscar um produto específico no catálogo."""

import app.services.catalog_service as legacy


class GetProductService:
    def execute(
        self,
        company_id: int,
        *,
        product_id: int | None = None,
        sku: str | None = None,
    ):
        return legacy.CatalogService.get(
            company_id,
            product_id=product_id,
            sku=sku,
        )


__all__ = ["GetProductService"]
