"""Use case for clearing a conversation's unread counter."""

import app.services.conversation_service as legacy


class MarkConversationReadService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        *,
        commit: bool = True,
    ):
        return legacy.ConversationService.mark_read(
            company_id,
            conversation_id,
            commit=commit,
        )


__all__ = ["MarkConversationReadService"]
