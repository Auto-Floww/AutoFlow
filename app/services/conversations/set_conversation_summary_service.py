"""Use case for persisting a conversation summary and cursor."""

import app.services.conversation_service as legacy


class SetConversationSummaryService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        *,
        summary: str,
        summarized_through_message_id: int | None = None,
        commit: bool = True,
    ):
        return legacy.ConversationService.set_summary(
            company_id,
            conversation_id,
            summary=summary,
            summarized_through_message_id=summarized_through_message_id,
            commit=commit,
        )


__all__ = ["SetConversationSummaryService"]
