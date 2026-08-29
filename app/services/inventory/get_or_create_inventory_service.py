"""Use case for obtaining the inventory row for a product or variant."""

import app.services.inventory_service as legacy


class GetOrCreateInventoryService:
    def execute(
        self,
        company_id: int,
        *,
        product_id: int | None = None,
        variant_id: int | None = None,
        minimum_quantity: int = 0,
        commit: bool = True,
    ):
        return legacy.InventoryService.get_or_create(
            company_id,
            product_id=product_id,
            variant_id=variant_id,
            minimum_quantity=minimum_quantity,
            commit=commit,
        )


__all__ = ["GetOrCreateInventoryService"]
