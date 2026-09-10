"""Caso de uso para salvar o resumo de uma conversa e o cursor que indica até onde ela foi processada."""

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
