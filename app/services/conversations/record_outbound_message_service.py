"""Use case for recording an outbound message."""

import app.services.conversation_service as legacy


class RecordOutboundMessageService:
    def execute(
        self,
        company_id: int,
        *,
        conversation_id: int,
        content: str,
        sender_type: str = "AI",
        sender_user_id: int | None = None,
        reply_to_id: int | None = None,
        ai_metadata: dict | None = None,
        idempotency_key: str | None = None,
        commit: bool = True,
    ):
        return legacy.ConversationService.record_outbound(
            company_id,
            conversation_id=conversation_id,
            content=content,
            sender_type=sender_type,
            sender_user_id=sender_user_id,
            reply_to_id=reply_to_id,
            ai_metadata=ai_metadata,
            idempotency_key=idempotency_key,
            commit=commit,
        )


__all__ = ["RecordOutboundMessageService"]
