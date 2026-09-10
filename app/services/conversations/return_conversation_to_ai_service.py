"""Caso de uso para devolver o controle de uma conversa à IA."""

import app.services.conversation_service as legacy


class ReturnConversationToAiService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        *,
        user_id: int | None = None,
        commit: bool = True,
    ):
        return legacy.ConversationService.return_to_ai(
            company_id,
            conversation_id,
            user_id=user_id,
            commit=commit,
        )


__all__ = ["ReturnConversationToAiService"]
