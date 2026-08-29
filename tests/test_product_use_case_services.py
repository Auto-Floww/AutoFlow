"""Behavioral coverage for the product use-case Services."""

from app.extensions import db
from app.models import Inventory, Product
from app.services.products import (
    ArchiveProductService,
    CreateProductService,
    CreateProductVariantService,
    ListProductsService,
    UpdateProductService,
)


def test_product_use_cases_execute_the_catalog_lifecycle(app, company_factory):
    company = company_factory(name="Catalogo Alpha")

    product = CreateProductService().execute(
        company.id,
        name="Camiseta",
        sku="CAM-1",
        price="79.90",
        minimum_quantity=2,
        initial_stock=8,
    )

    inventory = Inventory.for_company(company.id).filter_by(product_id=product.id).one()
    assert inventory.quantity == 8
    assert inventory.minimum_quantity == 2
    assert ListProductsService().execute(company.id, search="Camis").all() == [product]

    updated = UpdateProductService().execute(
        company.id,
        product.id,
        name="Camiseta Premium",
        promotional_price="69.90",
    )
    assert updated.name == "Camiseta Premium"

    variant = CreateProductVariantService().execute(
        company.id,
        product.id,
        color="Preta",
        size="M",
        sku="CAM-1-P-M",
        initial_stock=3,
    )
    assert variant.inventory.quantity == 3

    archived = ArchiveProductService().execute(company.id, product.id)
    assert archived.is_active is False
    assert all(item.is_active is False for item in archived.variants)


def test_list_products_service_never_crosses_tenants(app, company_factory):
    alpha = company_factory(name="Alpha")
    beta = company_factory(name="Beta")
    Product.create(company_id=beta.id, name="Segredo", sku="B-1", price="10.00")

    assert ListProductsService().execute(alpha.id).all() == []
    assert [item.name for item in ListProductsService().execute(beta.id).all()] == [
        "Segredo"
    ]

    db.session.rollback()
