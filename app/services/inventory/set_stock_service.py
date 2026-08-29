"""Use case for setting an absolute inventory quantity."""

import app.services.inventory_service as legacy


class SetStockService:
    def execute(
        self,
        company_id: int,
        inventory_id: int,
        *,
        quantity: int,
        **kwargs,
    ):
        return legacy.InventoryService.set_stock(
            company_id,
            inventory_id,
            quantity=quantity,
            **kwargs,
        )


__all__ = ["SetStockService"]
