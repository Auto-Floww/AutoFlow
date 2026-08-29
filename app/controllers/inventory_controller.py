"""Controller HTTP de saldos e razao imutavel de estoque."""

from __future__ import annotations

from decimal import Decimal
from flask import Blueprint, render_template, request
from flask_login import current_user, login_required
from types import SimpleNamespace

from app.extensions import db, limiter
from app.models import Inventory, InventoryMovement, Product, ProductVariant
from app.controllers.http import failure, model_dict, payload, record_audit, success
from app.services.exceptions import DomainError
from app.services.inventory import (
    AdjustStockService,
    ListInventoryHistoryService,
    ListLowStockInventoryService,
    SetStockService,
    UpdateMinimumInventoryService,
)
from app.tenant import current_company_id, roles_required, tenant_get_or_404


bp = Blueprint("inventory", __name__, url_prefix="/inventory")


def _inventory_data(inventory: Inventory) -> dict:
    product = inventory.product or (inventory.variant.product if inventory.variant else None)
    return {
        **model_dict(
            inventory,
            "id",
            "product_id",
            "variant_id",
            "quantity",
            "reserved_quantity",
            "minimum_quantity",
            "created_at",
            "updated_at",
        ),
        "available_quantity": inventory.available_quantity,
        "is_low_stock": inventory.is_low_stock,
        "product_name": product.name if product else "Item removido",
        "variant_name": inventory.variant.name if inventory.variant else None,
        "sku": inventory.variant.sku if inventory.variant else (product.sku if product else None),
    }


@bp.get("")
@login_required
def index():
    company_id = current_company_id()
    search = request.args.get("q", "").strip()
    low_only = request.args.get("low_stock", "").lower() in {"1", "true", "yes"}
    query = Inventory.for_company(company_id).outerjoin(Product, Inventory.product_id == Product.id).outerjoin(
        ProductVariant, Inventory.variant_id == ProductVariant.id
    )
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                Product.name.ilike(pattern),
                Product.sku.ilike(pattern),
                ProductVariant.name.ilike(pattern),
                ProductVariant.sku.ilike(pattern),
            )
        )
    if low_only:
        query = query.filter(
            Inventory.quantity - Inventory.reserved_quantity <= Inventory.minimum_quantity
        )
    inventories = query.order_by(Inventory.updated_at.desc()).all()
    movements = (
        InventoryMovement.for_company(company_id)
        .order_by(InventoryMovement.created_at.desc())
        .limit(100)
        .all()
    )
    low_stock_count = len(ListLowStockInventoryService().execute(company_id))
    inventory_views = []
    total_units = 0
    total_value = Decimal("0")
    out_of_stock = 0
    categories = set()
    for item in inventories:
        product = item.product or (item.variant.product if item.variant else None)
        available = item.available_quantity
        total_units += available
        if available <= 0:
            out_of_stock += 1
        if product:
            categories.add(product.category) if product.category else None
            price = item.variant.effective_price if item.variant else product.effective_price
            total_value += Decimal(price or 0) * available
        last_movement = item.movements.order_by(InventoryMovement.created_at.desc()).first()
        inventory_views.append(
            SimpleNamespace(
                id=item.id,
                quantity=available,
                physical_quantity=item.quantity,
                minimum_stock=item.minimum_quantity,
                product=product,
                variant_label=(
                    item.variant.name
                    or " / ".join(filter(None, (item.variant.color, item.variant.size)))
                    if item.variant
                    else None
                ),
                sku=item.variant.sku if item.variant else (product.sku if product else None),
                last_movement_label=(
                    last_movement.created_at.strftime("%d/%m/%Y %H:%M")
                    if last_movement
                    else "Sem movimentacao"
                ),
                last_movement_type_label=(last_movement.movement_type if last_movement else ""),
            )
        )
    movement_views = []
    for item in movements:
        inventory_item = item.inventory
        product = inventory_item.product or (
            inventory_item.variant.product if inventory_item.variant else None
        )
        movement_views.append(
            SimpleNamespace(
                id=item.id,
                type={"IN": "ENTRY", "OUT": "EXIT"}.get(item.movement_type, item.movement_type),
                product_name=product.name if product else "Item removido",
                variant_label=inventory_item.variant.name if inventory_item.variant else "",
                reference=item.reason or item.reference_id,
                quantity=abs(item.quantity_delta),
                created_label=item.created_at.strftime("%d/%m/%Y %H:%M"),
                user_name=item.actor_user.name if item.actor_user else "Sistema",
            )
        )
    inventory_stats = SimpleNamespace(
        total_units=total_units,
        total_skus=len(inventories),
        total_value_label=(
            "R$ " + f"{total_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        ),
        low_stock=low_stock_count,
        out_of_stock=out_of_stock,
    )
    return render_template(
        "inventory/index.html",
        inventories=inventories,
        inventory_items=inventory_views,
        movements=movement_views,
        inventory_stats=inventory_stats,
        categories=sorted(categories),
        low_stock_count=low_stock_count,
        total_items=len(inventories),
        filters={"q": search, "low_stock": low_only},
    )


@bp.post("/movement")
@bp.post("/<int:inventory_id>/movement")
@login_required
@roles_required("ADMIN", "OWNER")
@limiter.limit("60 per minute")
def movement(inventory_id: int | None = None):
    data = payload()
    inventory_id = inventory_id or int(data.get("inventory_id", 0) or 0)
    if not inventory_id:
        return failure("Selecione um item do estoque.", status=422)
    movement_type = str(data.get("movement_type", data.get("type", "ADJUSTMENT"))).upper()
    movement_type = {"ENTRY": "IN", "EXIT": "OUT"}.get(movement_type, movement_type)
    reason = data.get("reason") or data.get("notes") or data.get("reference")
    try:
        if data.get("target_quantity") not in {None, ""} or movement_type == "ADJUSTMENT":
            target = data.get("target_quantity", data.get("quantity"))
            result = SetStockService().execute(
                current_company_id(),
                inventory_id,
                quantity=int(target),
                reason=reason,
                actor_user_id=current_user.id,
                idempotency_key=request.headers.get("Idempotency-Key"),
                commit=False,
            )
        else:
            quantity = int(data.get("quantity", 0) or 0)
            if quantity <= 0:
                return failure("Informe uma quantidade maior que zero.", status=422)
            delta = -quantity if movement_type == "OUT" else quantity
            result = AdjustStockService().execute(
                current_company_id(),
                inventory_id,
                quantity_delta=delta,
                movement_type=movement_type,
                reason=reason,
                actor_user_id=current_user.id,
                idempotency_key=request.headers.get("Idempotency-Key"),
                commit=False,
            )
    except (DomainError, ValueError) as exc:
        message = exc.message if isinstance(exc, DomainError) else "Quantidade invalida."
        status = exc.status_code if isinstance(exc, DomainError) else 422
        return failure(message, status=status)
    inventory = tenant_get_or_404(Inventory, inventory_id)
    record_audit(
        "inventory.movement",
        inventory,
        {"movement_id": getattr(result, "id", None), "type": movement_type},
    )
    db.session.commit()
    return success("Estoque atualizado.", data=_inventory_data(inventory), endpoint="inventory.index", status=201)


@bp.patch("/<int:inventory_id>/minimum")
@bp.post("/<int:inventory_id>/minimum")
@login_required
@roles_required("ADMIN", "OWNER")
def update_minimum(inventory_id: int):
    try:
        minimum = int(payload().get("minimum_quantity", 0))
        if minimum < 0:
            raise ValueError
    except (TypeError, ValueError):
        return failure("Estoque minimo invalido.", status=422)
    inventory = UpdateMinimumInventoryService().execute(
        current_company_id(), inventory_id, minimum, commit=False
    )
    record_audit("inventory.minimum", inventory, {"minimum_quantity": minimum})
    db.session.commit()
    return success("Estoque minimo atualizado.", data=_inventory_data(inventory))


@bp.get("/<int:inventory_id>/history")
@login_required
def history(inventory_id: int):
    inventory, movements = ListInventoryHistoryService().execute(
        current_company_id(), inventory_id, limit=250
    )
    return {
        "inventory": _inventory_data(inventory),
        "movements": [
            model_dict(
                item,
                "id",
                "movement_type",
                "quantity_delta",
                "quantity_before",
                "quantity_after",
                "reason",
                "created_at",
            )
            for item in movements
        ],
    }


class InventoryController:
    """Handlers HTTP do dominio de estoque."""

    index = staticmethod(index)
    movement = staticmethod(movement)
    update_minimum = staticmethod(update_minimum)
    history = staticmethod(history)


for _endpoint, _handler in {
    "index": InventoryController.index,
    "movement": InventoryController.movement,
    "update_minimum": InventoryController.update_minimum,
    "history": InventoryController.history,
}.items():
    bp.view_functions[_endpoint] = _handler

del _endpoint, _handler
