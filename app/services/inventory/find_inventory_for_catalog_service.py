"""Use case for resolving catalog inventory filters."""

import app.services.inventory_service as legacy


class FindInventoryForCatalogService:
    def execute(
        self,
        company_id: int,
        *,
        product_id: int | None = None,
        variant_id: int | None = None,
        sku: str | None = None,
        color: str | None = None,
        size: str | None = None,
    ):
        return legacy.InventoryService.find_for_catalog(
            company_id,
            product_id=product_id,
            variant_id=variant_id,
            sku=sku,
            color=color,
            size=size,
        )


__all__ = ["FindInventoryForCatalogService"]
