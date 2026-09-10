"""Caso de uso para montar o histórico recente de mensagens em um formato compatível com a Groq."""

import app.services.conversation_service as legacy


class BuildGroqConversationHistoryService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        *,
        limit: int = 30,
        through_message_id: int | None = None,
    ) -> list[dict[str, str]]:
        return legacy.ConversationService.groq_history(
            company_id,
            conversation_id,
            limit=limit,
            through_message_id=through_message_id,
        )


__all__ = ["BuildGroqConversationHistoryService"]
