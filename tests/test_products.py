"""Catálogo de produtos, variantes e permissões."""

from app.extensions import db
from app.models import Inventory, InventoryMovement, Product


def test_owner_creates_product_and_initial_inventory(
    client, login_as, tenant_user
):
    login_as(tenant_user)

    response = client.post(
        "/products",
        json={
            "name": "Camiseta Essential",
            "sku": "CAM-001",
            "category": "Vestuário",
            "brand": "AutoFlow",
            "price": "89,90",
            "stock": 12,
            "minimum_quantity": 3,
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["data"]["sku"] == "CAM-001"
    product = db.session.get(Product, body["data"]["id"])
    inventory = Inventory.query.filter_by(product_id=product.id).one()
    movement = InventoryMovement.query.filter_by(inventory_id=inventory.id).one()
    assert product.company_id == tenant_user.company_id
    assert str(product.price) == "89.90"
    assert inventory.quantity == 12
    assert movement.quantity_before == 0
    assert movement.quantity_after == 12


def test_product_update_and_archive_preserve_record(
    client, login_as, tenant_user
):
    product = Product(
        company_id=tenant_user.company_id,
        name="Produto antigo",
        sku="OLD-1",
        price="10.00",
    )
    db.session.add(product)
    db.session.commit()
    login_as(tenant_user)

    updated = client.patch(
        f"/products/{product.id}",
        json={"name": "Produto novo", "promotional_price": "8.50"},
    )
    archived = client.delete(f"/products/{product.id}", json={})

    assert updated.status_code == 200
    assert updated.get_json()["data"]["name"] == "Produto novo"
    assert archived.status_code == 200
    db.session.refresh(product)
    assert product.is_active is False


def test_agent_cannot_mutate_catalog(client, login_as, user_factory):
    agent = user_factory(role="AGENT")
    login_as(agent)

    response = client.post(
        "/products",
        json={"name": "Negado", "sku": "NOPE", "price": "1.00"},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 403
    assert Product.query.filter_by(sku="NOPE").first() is None
