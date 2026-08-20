"""Clientes, normalização de telefone e CRM."""

from app.extensions import db
from app.models import Customer, Notification


def test_create_customer_normalizes_phone_and_rejects_duplicate(
    client, login_as, tenant_user
):
    login_as(tenant_user)
    data = {
        "name": "João Cliente",
        "phone": "(11) 98888-7777",
        "email": "joao@example.com",
        "organization": "Mercado João",
    }

    created = client.post("/customers", json=data)
    duplicate = client.post("/customers", json={**data, "name": "Outro João"})

    assert created.status_code == 201
    assert duplicate.status_code == 409
    customer = db.session.get(Customer, created.get_json()["data"]["id"])
    assert customer.phone_normalized == "5511988887777"
    assert customer.organization == "Mercado João"


def test_move_customer_through_crm(client, login_as, tenant_user):
    customer = Customer(
        company_id=tenant_user.company_id,
        name="Maria",
        phone="+5511999991111",
        phone_normalized="5511999991111",
    )
    db.session.add(customer)
    db.session.commit()
    login_as(tenant_user)

    moved = client.post(
        f"/customers/{customer.id}/stage", json={"stage": "QUALIFICADO"}
    )
    invalid = client.post(
        f"/customers/{customer.id}/stage", json={"stage": "INVENTADO"}
    )

    assert moved.status_code == 200
    assert moved.get_json()["data"]["stage"] == "QUALIFICADO"
    assert invalid.status_code == 422
    db.session.refresh(customer)
    assert customer.crm_stage == "QUALIFICADO"


def test_crm_opportunity_fields_are_persisted_and_rendered(
    client, login_as, tenant_user
):
    customer = Customer(
        company_id=tenant_user.company_id,
        name="Empresa Potencial",
        phone="+5511999991212",
        phone_normalized="5511999991212",
    )
    db.session.add(customer)
    db.session.commit()
    login_as(tenant_user)

    response = client.post(
        "/customers",
        json={
            "customer_id": customer.id,
            "stage": "PROPOSAL",
            "opportunity_title": "Plano anual",
            "opportunity_value": "12.345,67",
            "next_action": "Retornar na sexta-feira",
        },
    )

    assert response.status_code == 200
    db.session.refresh(customer)
    assert customer.crm_stage == "PROPOSTA"
    assert str(customer.opportunity_value) == "12345.67"
    assert customer.opportunity_title == "Plano anual"
    assert customer.next_action == "Retornar na sexta-feira"
    notification = Notification.query.filter_by(
        company_id=tenant_user.company_id,
        notification_type="IMPORTANT_OPPORTUNITY",
    ).one()
    assert notification.data_json == {
        "customer_id": customer.id,
        "stage": "PROPOSTA",
    }
    page = client.get("/customers/crm")
    assert "R$ 12.345,67" in page.get_data(as_text=True)
