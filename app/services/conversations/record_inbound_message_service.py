"""Use case for recording an idempotent inbound message."""

import app.services.conversation_service as legacy


class RecordInboundMessageService:
    def execute(
        self,
        company_id: int,
        *,
        conversation_id: int,
        content: str,
        external_message_id: str,
        message_type: str = "TEXT",
        payload: dict | None = None,
        commit: bool = True,
    ):
        return legacy.ConversationService.record_inbound(
            company_id,
            conversation_id=conversation_id,
            content=content,
            external_message_id=external_message_id,
            message_type=message_type,
            payload=payload,
            commit=commit,
        )


__all__ = ["RecordInboundMessageService"]
