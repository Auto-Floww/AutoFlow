"""Focused behavior tests for customer and inventory use cases."""

import pytest

from app.extensions import db
from app.models import Customer, Inventory, InventoryMovement, Product
from app.services.customers import ArchiveCustomerService
from app.services.exceptions import NotFoundError, ValidationError
from app.services.inventory import (
    ListInventoryHistoryService,
    UpdateMinimumInventoryService,
)


def _customer(company_id: int, *, suffix: str) -> Customer:
    customer = Customer(
        company_id=company_id,
        name=f"Cliente {suffix}",
        phone=f"+55119999{suffix}",
        phone_normalized=f"55119999{suffix}",
    )
    db.session.add(customer)
    db.session.flush()
    return customer


def _inventory(company_id: int, *, suffix: str, minimum_quantity: int = 2) -> Inventory:
    product = Product(
        company_id=company_id,
        name=f"Produto {suffix}",
        sku=f"SKU-{suffix}",
        price="10.00",
    )
    db.session.add(product)
    db.session.flush()
    inventory = Inventory(
        company_id=company_id,
        product_id=product.id,
        quantity=10,
        minimum_quantity=minimum_quantity,
    )
    db.session.add(inventory)
    db.session.flush()
    return inventory


def test_archive_customer_is_tenant_scoped_and_honors_commit(app, company_factory):
    company = company_factory(name="Empresa dona")
    other_company = company_factory(name="Outra empresa")
    customer = _customer(company.id, suffix="1001")
    foreign_customer = _customer(other_company.id, suffix="2002")
    db.session.commit()

    service = ArchiveCustomerService()
    archived = service.execute(company.id, customer.id, False)
    assert archived.status == "INACTIVE"
    db.session.rollback()
    assert db.session.get(Customer, customer.id).status == "ACTIVE"

    archived = service.execute(company.id, customer.id)
    db.session.expire_all()
    assert archived.status == "INACTIVE"
    assert db.session.get(Customer, customer.id).status == "INACTIVE"

    with pytest.raises(NotFoundError):
        service.execute(company.id, foreign_customer.id)


def test_inventory_history_is_bounded_ordered_and_tenant_safe(app, company_factory):
    company = company_factory(name="Empresa dona")
    other_company = company_factory(name="Outra empresa")
    inventory = _inventory(company.id, suffix="OWN")
    foreign_inventory = _inventory(other_company.id, suffix="OTHER")
    first = InventoryMovement(
        company_id=company.id,
        inventory=inventory,
        movement_type="IN",
        quantity_delta=1,
        quantity_before=8,
        quantity_after=9,
    )
    second = InventoryMovement(
        company_id=company.id,
        inventory=inventory,
        movement_type="IN",
        quantity_delta=1,
        quantity_before=9,
        quantity_after=10,
    )
    foreign = InventoryMovement(
        company_id=other_company.id,
        inventory=foreign_inventory,
        movement_type="IN",
        quantity_delta=1,
        quantity_before=9,
        quantity_after=10,
    )
    db.session.add_all([first, second, foreign])
    db.session.commit()

    selected_inventory, movements = ListInventoryHistoryService().execute(
        company.id,
        inventory.id,
        1,
    )
    assert selected_inventory.id == inventory.id
    assert [movement.id for movement in movements] == [second.id]
    assert all(movement.company_id == company.id for movement in movements)

    with pytest.raises(NotFoundError):
        ListInventoryHistoryService().execute(company.id, foreign_inventory.id)


def test_update_inventory_minimum_validates_and_honors_commit(app, company_factory):
    company = company_factory()
    inventory = _inventory(company.id, suffix="MIN", minimum_quantity=2)
    db.session.commit()
    service = UpdateMinimumInventoryService()

    updated = service.execute(company.id, inventory.id, 7, False)
    assert updated.minimum_quantity == 7
    db.session.rollback()
    assert db.session.get(Inventory, inventory.id).minimum_quantity == 2

    with pytest.raises(ValidationError, match="cannot be negative"):
        service.execute(company.id, inventory.id, -1)

    service.execute(company.id, inventory.id, 5)
    db.session.expire_all()
    assert db.session.get(Inventory, inventory.id).minimum_quantity == 5
