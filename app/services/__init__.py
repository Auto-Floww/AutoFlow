"""Application use cases, grouped by domain.

New code imports a concrete class from ``app.services.<domain>`` and invokes
its ``execute()`` method. The lazy names below only preserve older integrations
while they migrate from the former multi-action facades.
"""

from __future__ import annotations

from importlib import import_module


_COMPATIBILITY_EXPORTS = {
    "AppointmentService": ("app.services.appointment_service", "AppointmentService"),
    "CatalogService": ("app.services.catalog_service", "CatalogService"),
    "ConversationService": ("app.services.conversation_service", "ConversationService"),
    "CustomerService": ("app.services.customer_service", "CustomerService"),
    "DeliveryService": ("app.services.delivery_service", "DeliveryService"),
    "EmailService": ("app.services.email_service", "EmailService"),
    "GroqService": ("app.services.groq_service", "GroqService"),
    "InventoryService": ("app.services.inventory_service", "InventoryService"),
    "KnowledgeService": ("app.services.knowledge_service", "KnowledgeService"),
    "NotificationService": (
        "app.services.notification_service",
        "NotificationService",
    ),
    "OutboxService": ("app.services.outbox_service", "OutboxService"),
    "QuotaService": ("app.services.quota_service", "QuotaService"),
    "WhatsAppService": ("app.services.whatsapp_service", "WhatsAppService"),
}

__all__: list[str] = []


def __getattr__(name: str):
    """Resolve a former facade lazily without advertising it as the new API."""

    target = _COMPATIBILITY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
