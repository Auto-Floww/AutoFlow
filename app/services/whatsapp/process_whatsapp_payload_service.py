"""Use case for validating scope and persisting WhatsApp webhook events."""

from typing import Any

import app.services.whatsapp_service as legacy


class ProcessWhatsAppPayloadService:
    def __init__(self, whatsapp_gateway=None):
        self.whatsapp_gateway = whatsapp_gateway or legacy.WhatsAppService()

    def execute(
        self,
        payload: dict[str, Any],
        *,
        allowed_instances: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        return self.whatsapp_gateway.process_payload(
            payload,
            allowed_instances=allowed_instances,
        )


__all__ = ["ProcessWhatsAppPayloadService"]
