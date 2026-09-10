"""Caso de uso para buscar um registro específico do estoque pertencente a um determinado tenant (empresa ou organização)."""

import app.services.inventory_service as legacy


class GetInventoryService:
    def execute(self, company_id: int, inventory_id: int, *, lock: bool = False):
        return legacy.InventoryService.get(company_id, inventory_id, lock=lock)


__all__ = ["GetInventoryService"]
