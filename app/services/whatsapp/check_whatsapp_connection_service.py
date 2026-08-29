"""Use case for checking and persisting a WhatsApp connection state."""

import app.services.whatsapp_service as legacy


class CheckWhatsAppConnectionService:
    def __init__(self, whatsapp_gateway=None):
        self.whatsapp_gateway = whatsapp_gateway or legacy.WhatsAppService()

    def execute(
        self,
        company_id: int,
        integration_id: int | None = None,
    ) -> dict:
        return self.whatsapp_gateway.check_connection(company_id, integration_id)


__all__ = ["CheckWhatsAppConnectionService"]
