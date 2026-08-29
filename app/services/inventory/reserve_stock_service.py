"""Use case for reserving available inventory."""

import app.services.inventory_service as legacy


class ReserveStockService:
    def execute(
        self,
        company_id: int,
        inventory_id: int,
        *,
        quantity: int,
        idempotency_key: str | None = None,
        commit: bool = True,
    ):
        return legacy.InventoryService.reserve(
            company_id,
            inventory_id,
            quantity=quantity,
            idempotency_key=idempotency_key,
            commit=commit,
        )


__all__ = ["ReserveStockService"]
