"""Structural contract for the HTTP Controller layer and thin route wiring."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

CONTROLLERS = {
    "appointments_controller": "AppointmentsController",
    "auth_controller": "AuthController",
    "conversations_controller": "ConversationsController",
    "customers_controller": "CustomersController",
    "dashboard_controller": "DashboardController",
    "delivery_controller": "DeliveryController",
    "faq_controller": "FaqController",
    "inventory_controller": "InventoryController",
    "products_controller": "ProductsController",
    "settings_controller": "SettingsController",
    "whatsapp_controller": "WhatsAppController",
}


@pytest.mark.parametrize(("module_name", "class_name"), CONTROLLERS.items())
def test_each_blueprint_is_bound_to_a_controller_class(module_name, class_name):
    module = importlib.import_module(f"app.controllers.{module_name}")
    controller = getattr(module, class_name)

    assert module.bp.view_functions
    for endpoint, view_func in module.bp.view_functions.items():
        assert getattr(controller, endpoint) is view_func


def test_whatsapp_qrcode_blueprint_is_bound_to_its_controller(app):
    module = importlib.import_module(
        "app.controllers.whatsapp.whatsapp_qrcode_controller"
    )

    view_func = app.view_functions["whatsapp_qrcode_controller.create"]
    assert inspect.unwrap(view_func).__self__ is module._controller
    assert module._controller.create.__func__ is module.WhatsAppQrCodeController.create


@pytest.mark.parametrize(
    "route_module",
    sorted((ROOT / "app" / "routes").glob("*.py")),
    ids=lambda path: path.name,
)
def test_route_modules_are_wiring_only(route_module: Path):
    tree = ast.parse(route_module.read_text(encoding="utf-8"), filename=str(route_module))
    declarations = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert declarations == []

    if route_module.name != "__init__.py":
        imported_modules = {
            node.module or ""
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
        }
        imported_modules.update(
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert any(name.startswith("app.controllers") for name in imported_modules)


def test_parallel_backend_package_was_removed():
    assert not (ROOT / "backend").exists()
