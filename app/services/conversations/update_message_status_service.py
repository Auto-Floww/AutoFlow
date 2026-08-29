"""Use case for applying a provider delivery status to a message."""

import app.services.conversation_service as legacy


class UpdateMessageStatusService:
    def execute(
        self,
        company_id: int,
        external_message_id: str,
        status: str,
        *,
        timestamp=None,
        error_message: str | None = None,
        commit: bool = True,
    ):
        return legacy.ConversationService.update_message_status(
            company_id,
            external_message_id,
            status,
            timestamp=timestamp,
            error_message=error_message,
            commit=commit,
        )


__all__ = ["UpdateMessageStatusService"]
