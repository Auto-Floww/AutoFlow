"""Catálogo de produtos, variantes e permissões."""

import pytest

from app.extensions import db
from app.models import Inventory, InventoryMovement, Product, ProductVariant
from app.services.ai_tools import build_default_registry
from app.services.exceptions import NotFoundError
from app.services.tool_registry import ToolContext


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


def test_ai_catalog_tools_never_return_inactive_products_or_variants(tenant_user):
    active_product = Product(
        company_id=tenant_user.company_id,
        name="Camisa ativa",
        sku="CAM-A",
        price="50.00",
    )
    inactive_product = Product(
        company_id=tenant_user.company_id,
        name="Camisa arquivada",
        sku="CAM-X",
        price="40.00",
        is_active=False,
    )
    db.session.add_all([active_product, inactive_product])
    db.session.flush()
    active_variant = ProductVariant(
        company_id=tenant_user.company_id,
        product_id=active_product.id,
        name="Azul M",
        sku="CAM-A-M",
        is_active=True,
    )
    inactive_variant = ProductVariant(
        company_id=tenant_user.company_id,
        product_id=active_product.id,
        name="Vermelha G",
        sku="CAM-A-G",
        is_active=False,
    )
    archived_variant = ProductVariant(
        company_id=tenant_user.company_id,
        product_id=inactive_product.id,
        name="Preta P",
        sku="CAM-X-P",
        is_active=True,
    )
    db.session.add_all([active_variant, inactive_variant, archived_variant])
    db.session.flush()
    db.session.add(
        Inventory(
            company_id=tenant_user.company_id,
            variant_id=inactive_variant.id,
            quantity=9,
        )
    )
    db.session.commit()
    registry = build_default_registry()
    context = ToolContext(company_id=tenant_user.company_id)

    search = registry.execute("search_products", {}, context)
    assert search["ok"] is True
    assert [item["id"] for item in search["data"]] == [active_product.id]
    assert [item["sku"] for item in search["data"][0]["variants"]] == ["CAM-A-M"]

    active_lookup = registry.execute(
        "get_product", {"sku": "CAM-A-M"}, context
    )
    assert active_lookup["ok"] is True
    assert [item["sku"] for item in active_lookup["data"]["variants"]] == ["CAM-A-M"]
    with pytest.raises(NotFoundError):
        registry.execute("get_product", {"sku": "CAM-A-G"}, context)
    with pytest.raises(NotFoundError):
        registry.execute("get_product", {"product_id": inactive_product.id}, context)
    with pytest.raises(NotFoundError):
        registry.execute("get_product", {"sku": "CAM-X-P"}, context)

    inventory = registry.execute(
        "check_inventory", {"variant_id": inactive_variant.id}, context
    )
    assert inventory == {"ok": True, "data": []}
