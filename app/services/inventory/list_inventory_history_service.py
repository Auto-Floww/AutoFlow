"""Use case for listing a tenant-scoped inventory movement history."""

from app.models import Inventory, InventoryMovement
from app.services.tenancy import tenant_get


class ListInventoryHistoryService:
    def execute(
        self,
        company_id: int,
        inventory_id: int,
        limit: int = 250,
    ) -> tuple[Inventory, list[InventoryMovement]]:
        inventory = tenant_get(Inventory, company_id, inventory_id)
        bounded_limit = min(max(int(limit), 1), 250)
        movements = (
            InventoryMovement.for_company(company_id)
            .filter(InventoryMovement.inventory_id == inventory.id)
            .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
            .limit(bounded_limit)
            .all()
        )
        return inventory, movements


__all__ = ["ListInventoryHistoryService"]
