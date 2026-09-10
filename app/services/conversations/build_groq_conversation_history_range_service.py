"""Caso de uso para montar um intervalo limitado do histórico de mensagens da Groq."""

import app.services.conversation_service as legacy


class BuildGroqConversationHistoryRangeService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        *,
        after_message_id: int = 0,
        through_message_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, str]]:
        return legacy.ConversationService.groq_history_range(
            company_id,
            conversation_id,
            after_message_id=after_message_id,
            through_message_id=through_message_id,
            limit=limit,
        )


__all__ = ["BuildGroqConversationHistoryRangeService"]
