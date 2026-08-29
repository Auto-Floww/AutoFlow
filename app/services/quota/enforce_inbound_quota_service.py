"""Use case for reserving inbound AI-message quota atomically."""

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
