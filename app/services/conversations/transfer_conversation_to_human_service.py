"""Caso de uso para pausar a IA e solicitar a transferência da conversa para um atendente humano."""

import app.services.conversation_service as legacy


class TransferConversationToHumanService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        *,
        reason: str | None = None,
        commit: bool = True,
    ):
        return legacy.ConversationService.transfer_to_human(
            company_id,
            conversation_id,
            reason=reason,
            commit=commit,
        )


__all__ = ["TransferConversationToHumanService"]
