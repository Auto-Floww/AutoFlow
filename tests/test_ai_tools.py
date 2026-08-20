"""Allow-list e isolamento das ferramentas disponibilizadas ao modelo."""

import pytest

from app.extensions import db
from app.models import Inventory, Product
from app.services.ai_tools import build_default_registry
from app.services.catalog_service import CatalogService
from app.services.exceptions import ValidationError
from app.services.tool_registry import ToolContext


EXPECTED_TOOLS = {
    "search_products",
    "get_product",
    "check_inventory",
    "get_delivery_options",
    "get_business_hours",
    "search_faq",
    "search_knowledge",
    "get_available_appointments",
    "create_appointment",
    "cancel_appointment",
    "get_customer",
    "update_customer",
    "add_customer_tag",
    "transfer_to_human",
}


def test_registry_exposes_only_explicit_tools():
    names = {
        item["function"]["name"] for item in build_default_registry().schemas()
    }

    assert names == EXPECTED_TOOLS


def test_model_cannot_override_trusted_company_context(monkeypatch, tenant_user):
    registry = build_default_registry()
    called_with = []
    monkeypatch.setattr(
        CatalogService,
        "search",
        staticmethod(
            lambda company_id, **kwargs: called_with.append(company_id) or []
        ),
    )
    context = ToolContext(company_id=tenant_user.company_id)

    result = registry.execute("search_products", {"query": "camisa"}, context)
    assert result == {"ok": True, "data": []}
    assert called_with == [tenant_user.company_id]

    with pytest.raises(ValidationError, match="Protected context"):
        registry.execute(
            "search_products",
            {"query": "camisa", "company_id": tenant_user.company_id + 999},
            context,
        )


def test_check_inventory_returns_only_context_tenant(
    tenant_user, company_factory
):
    other = company_factory(name="Outra empresa")
    own_product = Product(
        company_id=tenant_user.company_id,
        name="Camiseta preta",
        sku="CAM-PRETA-M",
        price="80.00",
    )
    foreign_product = Product(
        company_id=other.id,
        name="Camiseta privada",
        sku="CAM-PRETA-M",
        price="180.00",
    )
    db.session.add_all([own_product, foreign_product])
    db.session.flush()
    db.session.add_all(
        [
            Inventory(
                company_id=tenant_user.company_id,
                product_id=own_product.id,
                quantity=4,
            ),
            Inventory(company_id=other.id, product_id=foreign_product.id, quantity=99),
        ]
    )
    db.session.commit()

    result = build_default_registry().execute(
        "check_inventory",
        {"sku": "CAM-PRETA-M"},
        ToolContext(company_id=tenant_user.company_id),
    )

    assert result["ok"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["available_quantity"] == 4
    assert result["data"][0]["product_id"] == own_product.id


def test_unknown_tool_and_bad_arguments_are_safe(tenant_user):
    registry = build_default_registry()
    context = ToolContext(company_id=tenant_user.company_id)

    with pytest.raises(ValidationError):
        registry.execute("execute_sql", {}, context)
    with pytest.raises(ValidationError):
        registry.execute("check_inventory", "{invalid", context)

    error = registry.safe_error(RuntimeError("database password must not leak"))
    assert error["error"] == "tool_execution_failed"
    assert "password" not in error["message"]
