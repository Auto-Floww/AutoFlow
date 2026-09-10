"""Caso de uso para buscar uma conversa específica pertencente a um determinado tenant (cliente ou organização)."""

import app.services.conversation_service as legacy


class GetConversationService:
    def execute(self, company_id: int, conversation_id: int, *, lock: bool = False):
        return legacy.ConversationService.get(
            company_id,
            conversation_id,
            lock=lock,
        )


__all__ = ["GetConversationService"]
