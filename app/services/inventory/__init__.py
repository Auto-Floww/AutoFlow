"""Inventory use cases."""

from app.services.inventory.adjust_stock_service import AdjustStockService
from app.services.inventory.find_inventory_for_catalog_service import (
    FindInventoryForCatalogService,
)
from app.services.inventory.get_inventory_service import GetInventoryService
from app.services.inventory.get_or_create_inventory_service import GetOrCreateInventoryService
from app.services.inventory.list_low_stock_inventory_service import (
    ListLowStockInventoryService,
)
from app.services.inventory.list_inventory_history_service import ListInventoryHistoryService
from app.services.inventory.reserve_stock_service import ReserveStockService
from app.services.inventory.set_stock_service import SetStockService
from app.services.inventory.update_minimum_inventory_service import (
    UpdateMinimumInventoryService,
)

__all__ = [
    "AdjustStockService",
    "FindInventoryForCatalogService",
    "GetInventoryService",
    "GetOrCreateInventoryService",
    "ListLowStockInventoryService",
    "ListInventoryHistoryService",
    "ReserveStockService",
    "SetStockService",
    "UpdateMinimumInventoryService",
]
