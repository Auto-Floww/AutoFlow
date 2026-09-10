"""Caso de uso para listar os registros de produtos com estoque baixo."""

import app.services.inventory_service as legacy


class ListLowStockInventoryService:
    def execute(self, company_id: int):
        return legacy.InventoryService.low_stock(company_id)


__all__ = ["ListLowStockInventoryService"]
