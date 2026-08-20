"""Estoque transacional e razão de movimentações."""

from app.extensions import db
from app.models import Inventory, InventoryMovement, Product


def _inventory(company_id: int, *, quantity: int = 10) -> Inventory:
    product = Product(
        company_id=company_id,
        name="Caneca",
        sku="CAN-001",
        price="30.00",
    )
    db.session.add(product)
    db.session.flush()
    inventory = Inventory(
        company_id=company_id,
        product_id=product.id,
        quantity=quantity,
        minimum_quantity=2,
    )
    db.session.add(inventory)
    db.session.commit()
    return inventory


def test_stock_out_creates_immutable_balance_history(
    client, login_as, tenant_user
):
    inventory = _inventory(tenant_user.company_id, quantity=10)
    login_as(tenant_user)

    response = client.post(
        f"/inventory/{inventory.id}/movement",
        json={"movement_type": "OUT", "quantity": 4, "reason": "Venda #42"},
    )

    assert response.status_code == 201
    db.session.refresh(inventory)
    movement = InventoryMovement.query.filter_by(inventory_id=inventory.id).one()
    assert inventory.quantity == 6
    assert movement.quantity_delta == -4
    assert (movement.quantity_before, movement.quantity_after) == (10, 6)


def test_stock_cannot_become_negative(client, login_as, tenant_user):
    inventory = _inventory(tenant_user.company_id, quantity=2)
    login_as(tenant_user)

    response = client.post(
        f"/inventory/{inventory.id}/movement",
        json={"movement_type": "OUT", "quantity": 3},
    )

    assert response.status_code == 409
    db.session.refresh(inventory)
    assert inventory.quantity == 2


def test_movement_idempotency_prevents_duplicate_stock_change(
    client, login_as, tenant_user
):
    inventory = _inventory(tenant_user.company_id, quantity=1)
    login_as(tenant_user)
    headers = {"Idempotency-Key": "recebimento-123"}
    payload = {"movement_type": "IN", "quantity": 5}

    first = client.post(
        f"/inventory/{inventory.id}/movement", json=payload, headers=headers
    )
    second = client.post(
        f"/inventory/{inventory.id}/movement", json=payload, headers=headers
    )

    assert first.status_code == second.status_code == 201
    db.session.refresh(inventory)
    assert inventory.quantity == 6
    assert InventoryMovement.query.filter_by(inventory_id=inventory.id).count() == 1
