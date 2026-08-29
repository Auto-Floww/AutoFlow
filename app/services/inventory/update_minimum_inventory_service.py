"""Use case for changing the low-stock threshold of an inventory row."""

from app.extensions import db
from app.models import Inventory
from app.services.exceptions import ValidationError
from app.services.tenancy import tenant_get


class UpdateMinimumInventoryService:
    def execute(
        self,
        company_id: int,
        inventory_id: int,
        minimum_quantity: int,
        commit: bool = True,
    ) -> Inventory:
        minimum = int(minimum_quantity)
        if minimum < 0:
            raise ValidationError("Minimum quantity cannot be negative")
        inventory = tenant_get(Inventory, company_id, inventory_id, lock=True)
        inventory.minimum_quantity = minimum
        if commit:
            db.session.commit()
        return inventory


__all__ = ["UpdateMinimumInventoryService"]
