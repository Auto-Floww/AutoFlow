"""Use case for applying an auditable stock movement."""

import app.services.inventory_service as legacy


class AdjustStockService:
    def execute(
        self,
        company_id: int,
        inventory_id: int,
        *,
        quantity_delta: int,
        movement_type: str = "ADJUSTMENT",
        reason: str | None = None,
        actor_user_id: int | None = None,
        reference_type: str | None = None,
        reference_id: str | None = None,
        idempotency_key: str | None = None,
        commit: bool = True,
    ):
        return legacy.InventoryService.adjust_stock(
            company_id,
            inventory_id,
            quantity_delta=quantity_delta,
            movement_type=movement_type,
            reason=reason,
            actor_user_id=actor_user_id,
            reference_type=reference_type,
            reference_id=reference_id,
            idempotency_key=idempotency_key,
            commit=commit,
        )


__all__ = ["AdjustStockService"]
