"""Use case for creating a product, its variants, and initial inventory."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.extensions import db
from app.models import Product, ProductVariant
from app.services.inventory.adjust_stock_service import AdjustStockService
from app.services.inventory.get_or_create_inventory_service import (
    GetOrCreateInventoryService,
)
from app.services.exceptions import ValidationError


class CreateProductService:
    """Create the complete catalog aggregate in one transaction."""

    def __init__(
        self,
        inventory_service: GetOrCreateInventoryService | None = None,
        stock_service: AdjustStockService | None = None,
    ):
        self.inventory_service = inventory_service or GetOrCreateInventoryService()
        self.stock_service = stock_service or AdjustStockService()

    def execute(
        self,
        company_id: int,
        *,
        name: str,
        price,
        description: str | None = None,
        sku: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        promotional_price=None,
        image_url: str | None = None,
        is_active: bool = True,
        minimum_quantity: int = 0,
        initial_stock: int = 0,
        variants: Iterable[Mapping[str, Any]] | None = None,
        actor_user_id: int | None = None,
        commit: bool = True,
    ) -> Product:
        normalized_name = str(name).strip()
        if len(normalized_name) < 2:
            raise ValidationError("Informe o nome do produto")
        minimum_quantity = int(minimum_quantity or 0)
        initial_stock = int(initial_stock or 0)
        if minimum_quantity < 0 or initial_stock < 0:
            raise ValidationError("As quantidades de estoque nao podem ser negativas")

        product = Product.create(
            company_id=company_id,
            name=normalized_name[:180],
            description=self._text(description, 6000),
            sku=self._text(sku, 80),
            category=self._text(category, 100),
            brand=self._text(brand, 100),
            price=price,
            promotional_price=promotional_price,
            image_url=self._text(image_url, 500),
            is_active=bool(is_active),
            commit=False,
        )

        variant_specs = [dict(item) for item in (variants or [])]
        created_variant = False
        for spec in variant_specs:
            if not any(
                self._text(spec.get(field), maximum)
                for field, maximum in (("name", 180), ("color", 80), ("size", 80), ("sku", 80))
            ):
                continue
            created_variant = True
            variant = ProductVariant.create(
                company_id=company_id,
                product_id=product.id,
                name=self._text(spec.get("name"), 180)
                or " / ".join(
                    filter(
                        None,
                        (
                            self._text(spec.get("color"), 80),
                            self._text(spec.get("size"), 80),
                        ),
                    )
                )
                or None,
                color=self._text(spec.get("color"), 80),
                size=self._text(spec.get("size"), 80),
                sku=self._text(spec.get("sku"), 80),
                price=spec.get("price"),
                is_active=bool(spec.get("is_active", True)),
                commit=False,
            )
            inventory = self.inventory_service.execute(
                company_id,
                variant_id=variant.id,
                minimum_quantity=max(0, int(spec.get("minimum_quantity", minimum_quantity) or 0)),
                commit=False,
            )
            stock = int(spec.get("stock", 0) or 0)
            if stock < 0:
                raise ValidationError("O estoque inicial nao pode ser negativo")
            if stock:
                self.stock_service.execute(
                    company_id,
                    inventory.id,
                    quantity_delta=stock,
                    movement_type="IN",
                    reason="Estoque inicial da variante",
                    actor_user_id=actor_user_id,
                    commit=False,
                )

        if not created_variant:
            inventory = self.inventory_service.execute(
                company_id,
                product_id=product.id,
                minimum_quantity=minimum_quantity,
                commit=False,
            )
            if initial_stock:
                self.stock_service.execute(
                    company_id,
                    inventory.id,
                    quantity_delta=initial_stock,
                    movement_type="IN",
                    reason="Estoque inicial",
                    actor_user_id=actor_user_id,
                    commit=False,
                )

        db.session.commit() if commit else db.session.flush()
        return product

    @staticmethod
    def _text(value, maximum: int) -> str | None:
        if value is None:
            return None
        return str(value).strip()[:maximum] or None


__all__ = ["CreateProductService"]
