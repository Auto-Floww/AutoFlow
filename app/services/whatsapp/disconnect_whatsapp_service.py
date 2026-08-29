"""Use case for disconnecting the tenant WhatsApp integration."""

import app.services.whatsapp_service as legacy


class DisconnectWhatsAppService:
    def __init__(self, whatsapp_gateway=None):
        self.whatsapp_gateway = whatsapp_gateway or legacy.WhatsAppService()

    def execute(self, company_id: int) -> None:
        return self.whatsapp_gateway.disconnect(company_id)


__all__ = ["DisconnectWhatsAppService"]
