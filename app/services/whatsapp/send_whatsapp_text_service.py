"""Use case for sending a text through the configured WhatsApp integration."""

from typing import Any

import app.services.whatsapp_service as legacy


class SendWhatsAppTextService:
    def __init__(self, whatsapp_gateway=None):
        self.whatsapp_gateway = whatsapp_gateway or legacy.WhatsAppService()

    def execute(
        self,
        company_id: int,
        *,
        to: str,
        text: str,
        integration_id: int | None = None,
        reply_to_external_id: str | None = None,
    ) -> dict[str, Any]:
        return self.whatsapp_gateway.send_text(
            company_id,
            to=to,
            text=text,
            integration_id=integration_id,
            reply_to_external_id=reply_to_external_id,
        )


__all__ = ["SendWhatsAppTextService"]
