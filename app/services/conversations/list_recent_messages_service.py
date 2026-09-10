"""Caso de uso para listar uma quantidade limitada de mensagens recentes de uma conversa."""

import app.services.conversation_service as legacy


class ListRecentMessagesService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        *,
        limit: int = 30,
        through_message_id: int | None = None,
    ):
        return legacy.ConversationService.recent_messages(
            company_id,
            conversation_id,
            limit=limit,
            through_message_id=through_message_id,
        )


__all__ = ["ListRecentMessagesService"]
