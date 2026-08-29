"""Transactional inventory operations with an auditable movement ledger."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Inventory, InventoryMovement, Product, ProductVariant
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.tenancy import ensure_same_company, tenant_get


class InventoryOperations:
    @staticmethod
    def get(company_id: int, inventory_id: int, *, lock: bool = False) -> Inventory:
        return tenant_get(Inventory, company_id, inventory_id, lock=lock)

    @staticmethod
    def get_or_create(
        company_id: int,
        *,
        product_id: int | None = None,
        variant_id: int | None = None,
        minimum_quantity: int = 0,
        commit: bool = True,
    ) -> Inventory:
        if bool(product_id) == bool(variant_id):
            raise ValidationError("Select exactly one product or variant")
        if variant_id:
            variant = tenant_get(ProductVariant, company_id, variant_id)
            product_id_for_record = None
            ensure_same_company(company_id, variant.product)
            query = Inventory.query.filter_by(company_id=int(company_id), variant_id=variant.id)
        else:
            product = tenant_get(Product, company_id, product_id)
            product_id_for_record = product.id
            query = Inventory.query.filter_by(
                company_id=int(company_id), product_id=product.id, variant_id=None
            )
        inventory = query.one_or_none()
        if inventory is None:
            inventory = Inventory(
                company_id=int(company_id),
                product_id=product_id_for_record,
                variant_id=variant_id,
                minimum_quantity=max(0, int(minimum_quantity)),
            )
            db.session.add(inventory)
            try:
                db.session.flush()
                if commit:
                    db.session.commit()
            except IntegrityError:
                db.session.rollback()
                inventory = query.one()
        return inventory

    @staticmethod
    def find_for_catalog(
        company_id: int,
        *,
        product_id: int | None = None,
        variant_id: int | None = None,
        sku: str | None = None,
        color: str | None = None,
        size: str | None = None,
    ) -> list[Inventory]:
        if sku and not product_id and not variant_id:
            variant = ProductVariant.query.filter_by(
                company_id=int(company_id), sku=sku
            ).one_or_none()
            if variant:
                variant_id = variant.id
                sku = None
            else:
                product = Product.query.filter_by(
                    company_id=int(company_id), sku=sku
                ).one_or_none()
                if product is None:
                    return []
                product_id = product.id
                sku = None
        query = Inventory.for_company(company_id)
        variant_joined = False
        if variant_id:
            query = query.filter(Inventory.variant_id == variant_id)
        elif product_id:
            query = query.outerjoin(ProductVariant, Inventory.variant_id == ProductVariant.id).filter(
                db.or_(
                    Inventory.product_id == product_id,
                    ProductVariant.product_id == product_id,
                )
            )
            variant_joined = True
        elif sku:
            query = (
                query.outerjoin(Product, Inventory.product_id == Product.id)
                .outerjoin(ProductVariant, Inventory.variant_id == ProductVariant.id)
                .filter(db.or_(Product.sku == sku, ProductVariant.sku == sku))
            )
            variant_joined = True
        if (color or size) and not variant_joined:
            query = query.join(ProductVariant, Inventory.variant_id == ProductVariant.id)
            variant_joined = True
        if color:
            query = query.filter(
                db.func.lower(ProductVariant.color) == color.strip().lower()
            )
        if size:
            query = query.filter(db.func.lower(ProductVariant.size) == size.strip().lower())
        return query.all()

    @staticmethod
    def adjust_stock(
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
    ) -> InventoryMovement:
        movement_type = movement_type.upper()
        if movement_type not in {"IN", "OUT", "ADJUSTMENT"}:
            raise ValidationError("Invalid inventory movement type")
        delta = int(quantity_delta)
        if delta == 0:
            raise ValidationError("Inventory movement cannot be zero")
        if movement_type == "IN" and delta < 0:
            raise ValidationError("IN movement requires a positive quantity")
        if movement_type == "OUT" and delta > 0:
            delta = -delta
        if idempotency_key:
            existing = InventoryMovement.query.filter_by(
                company_id=int(company_id), idempotency_key=idempotency_key
            ).one_or_none()
            if existing:
                return existing
        inventory = tenant_get(Inventory, company_id, inventory_id, lock=True)
        before = inventory.quantity
        after = before + delta
        if after < inventory.reserved_quantity:
            raise ConflictError(
                "Insufficient available inventory",
                details={"available": inventory.available_quantity, "requested": abs(delta)},
            )
        movement = InventoryMovement(
            company_id=int(company_id),
            inventory=inventory,
            actor_user_id=actor_user_id,
            movement_type=movement_type,
            quantity_delta=delta,
            quantity_before=before,
            quantity_after=after,
            reason=(reason or "")[:255] or None,
            reference_type=(reference_type or "")[:64] or None,
            reference_id=(str(reference_id) if reference_id is not None else None),
            idempotency_key=idempotency_key,
        )
        inventory.quantity = after
        db.session.add(movement)
        try:
            db.session.flush()
            if inventory.is_low_stock:
                from app.services.notification_service import NotificationOperations

                catalog_name = (
                    inventory.variant.name
                    if inventory.variant and inventory.variant.name
                    else (
                        inventory.variant.product.name
                        if inventory.variant
                        else inventory.product.name
                    )
                )
                NotificationOperations.create(
                    company_id,
                    notification_type="LOW_STOCK",
                    title="Estoque baixo",
                    body=(
                        f"{catalog_name}: {inventory.available_quantity} unidade(s) disponível(is)."
                    ),
                    link_url="/inventory",
                    data={"inventory_id": inventory.id},
                    idempotency_key=f"low-stock-movement:{movement.id}",
                    commit=False,
                )
            if commit:
                db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            if idempotency_key:
                existing = InventoryMovement.query.filter_by(
                    company_id=int(company_id), idempotency_key=idempotency_key
                ).one_or_none()
                if existing:
                    return existing
            raise ConflictError("Inventory update conflicted with another operation") from exc
        return movement

    @staticmethod
    def set_stock(
        company_id: int,
        inventory_id: int,
        *,
        quantity: int,
        **kwargs,
    ) -> InventoryMovement | None:
        inventory = tenant_get(Inventory, company_id, inventory_id, lock=True)
        target = int(quantity)
        if target < inventory.reserved_quantity:
            raise ConflictError("Stock cannot be lower than reserved inventory")
        delta = target - inventory.quantity
        if not delta:
            return None
        return InventoryOperations.adjust_stock(
            company_id,
            inventory_id,
            quantity_delta=delta,
            movement_type="ADJUSTMENT",
            **kwargs,
        )

    @staticmethod
    def reserve(
        company_id: int,
        inventory_id: int,
        *,
        quantity: int,
        idempotency_key: str | None = None,
        commit: bool = True,
    ) -> InventoryMovement:
        amount = int(quantity)
        if amount <= 0:
            raise ValidationError("Reservation quantity must be positive")
        if idempotency_key:
            existing = InventoryMovement.query.filter_by(
                company_id=int(company_id), idempotency_key=idempotency_key
            ).one_or_none()
            if existing:
                return existing
        inventory = tenant_get(Inventory, company_id, inventory_id, lock=True)
        if inventory.available_quantity < amount:
            raise ConflictError("Insufficient available inventory")
        before = inventory.quantity
        inventory.reserved_quantity += amount
        movement = InventoryMovement(
            company_id=int(company_id),
            inventory=inventory,
            movement_type="RESERVE",
            quantity_delta=amount,
            quantity_before=before,
            quantity_after=before,
            idempotency_key=idempotency_key,
        )
        db.session.add(movement)
        if commit:
            db.session.commit()
        return movement

    @staticmethod
    def low_stock(company_id: int) -> list[Inventory]:
        # SQL expression accounts for reservations, unlike a Python property filter.
        return Inventory.for_company(company_id).filter(
            Inventory.quantity - Inventory.reserved_quantity <= Inventory.minimum_quantity
        ).all()


# Backwards-compatible alias; use-case Services live in ``app.services.inventory``.
InventoryService = InventoryOperations
adjust_stock = InventoryOperations.adjust_stock
