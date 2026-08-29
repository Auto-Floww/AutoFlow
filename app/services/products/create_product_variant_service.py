"""Use case for adding a variant and its initial inventory."""

from app.extensions import db
from app.models import Product, ProductVariant
from app.services.inventory.adjust_stock_service import AdjustStockService
from app.services.inventory.get_or_create_inventory_service import (
    GetOrCreateInventoryService,
)
from app.services.exceptions import ValidationError
from app.services.tenancy import tenant_get


class CreateProductVariantService:
    def execute(
        self,
        company_id: int,
        product_id: int,
        *,
        name: str | None = None,
        color: str | None = None,
        size: str | None = None,
        sku: str | None = None,
        price=None,
        is_active: bool = True,
        minimum_quantity: int = 0,
        initial_stock: int = 0,
        actor_user_id: int | None = None,
        commit: bool = True,
    ) -> ProductVariant:
        product = tenant_get(Product, company_id, product_id)
        minimum_quantity = int(minimum_quantity or 0)
        initial_stock = int(initial_stock or 0)
        if minimum_quantity < 0 or initial_stock < 0:
            raise ValidationError("As quantidades de estoque nao podem ser negativas")
        variant = ProductVariant.create(
            company_id=company_id,
            product_id=product.id,
            name=self._text(name, 180),
            color=self._text(color, 80),
            size=self._text(size, 80),
            sku=self._text(sku, 80),
            price=price,
            is_active=bool(is_active),
            commit=False,
        )
        inventory = GetOrCreateInventoryService().execute(
            company_id,
            variant_id=variant.id,
            minimum_quantity=minimum_quantity,
            commit=False,
        )
        if initial_stock:
            AdjustStockService().execute(
                company_id,
                inventory.id,
                quantity_delta=initial_stock,
                movement_type="IN",
                reason="Estoque inicial da variante",
                actor_user_id=actor_user_id,
                commit=False,
            )
        db.session.commit() if commit else db.session.flush()
        return variant

    @staticmethod
    def _text(value, maximum: int) -> str | None:
        return str(value).strip()[:maximum] or None if value is not None else None


__all__ = ["CreateProductVariantService"]
