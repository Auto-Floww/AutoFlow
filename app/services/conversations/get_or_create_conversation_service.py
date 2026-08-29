"""Use case for obtaining an active conversation for a customer."""

import app.services.conversation_service as legacy


class GetOrCreateConversationService:
    def execute(
        self,
        company_id: int,
        *,
        customer_id: int,
        channel: str = "WHATSAPP",
        external_id: str | None = None,
        whatsapp_integration_id: int | None = None,
        commit: bool = True,
    ):
        return legacy.ConversationService.get_or_create(
            company_id,
            customer_id=customer_id,
            channel=channel,
            external_id=external_id,
            whatsapp_integration_id=whatsapp_integration_id,
            commit=commit,
        )


__all__ = ["GetOrCreateConversationService"]
