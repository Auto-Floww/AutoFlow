"""Caso de uso para atribuir uma conversa a um atendente humano."""

import app.services.conversation_service as legacy


class ClaimConversationService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        *,
        user_id: int,
        commit: bool = True,
    ):
        return legacy.ConversationService.claim(
            company_id,
            conversation_id,
            user_id=user_id,
            commit=commit,
        )


__all__ = ["ClaimConversationService"]
