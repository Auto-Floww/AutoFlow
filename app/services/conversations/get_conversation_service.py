"""Use case for retrieving one tenant-scoped conversation."""

import app.services.conversation_service as legacy


class GetConversationService:
    def execute(self, company_id: int, conversation_id: int, *, lock: bool = False):
        return legacy.ConversationService.get(
            company_id,
            conversation_id,
            lock=lock,
        )


__all__ = ["GetConversationService"]
