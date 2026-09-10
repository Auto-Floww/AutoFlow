"""Caso de uso para reservar, de forma atômica, parte da cota de mensagens recebidas que serão processadas pela IA."""

import app.services.quota_service as legacy


class EnforceInboundQuotaService:
    def execute(
        self,
        company_id: int,
        *,
        sender: str,
        external_message_id: str,
    ):
        return legacy.QuotaService.enforce_inbound(
            company_id,
            sender=sender,
            external_message_id=external_message_id,
        )


__all__ = ["EnforceInboundQuotaService"]
