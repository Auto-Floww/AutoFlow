"""Barreiras de isolamento entre empresas."""

from app.extensions import db
from app.models import Customer, Product


def test_tenant_model_helpers_never_return_another_company(
    app, company_factory
):
    alpha = company_factory(name="Alpha")
    beta = company_factory(name="Beta")
    foreign_product = Product(
        company_id=beta.id,
        name="Produto da Beta",
        sku="BETA-1",
        price="10.00",
    )
    db.session.add(foreign_product)
    db.session.commit()

    assert Product.get_for_company(alpha.id, foreign_product.id) is None
    assert Product.get_for_company(beta.id, foreign_product.id) == foreign_product


def test_authenticated_user_cannot_read_foreign_product(
    client, login_as, user_factory, company_factory
):
    alpha = company_factory(name="Alpha")
    beta = company_factory(name="Beta")
    user = user_factory(company=alpha)
    foreign_product = Product(
        company_id=beta.id,
        name="Segredo da Beta",
        sku="SECRET-B",
        price="99.00",
    )
    db.session.add(foreign_product)
    db.session.commit()
    login_as(user)

    response = client.get(
        f"/products/{foreign_product.id}", headers={"Accept": "application/json"}
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_company_id_from_request_is_ignored(client, login_as, user_factory, company_factory):
    alpha = company_factory(name="Alpha")
    beta = company_factory(name="Beta")
    user = user_factory(company=alpha)
    login_as(user)

    response = client.post(
        "/customers",
        json={
            "name": "Cliente da Alpha",
            "phone": "+55 11 99999-0000",
            "company_id": beta.id,
        },
    )

    assert response.status_code == 201
    customer_id = response.get_json()["data"]["id"]
    customer = db.session.get(Customer, customer_id)
    assert customer.company_id == alpha.id
    assert customer.company_id != beta.id
