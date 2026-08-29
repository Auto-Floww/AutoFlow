"""Use case for generating a bounded conversation summary."""

import app.services.groq_service as legacy


class SummarizeConversationService:
    def __init__(self, ai_gateway=None):
        self.ai_gateway = ai_gateway or legacy.GroqService()

    def execute(
        self,
        conversation,
        *,
        after_message_id: int = 0,
        through_message_id: int | None = None,
    ) -> str:
        return self.ai_gateway.summarize_conversation(
            conversation,
            after_message_id=after_message_id,
            through_message_id=through_message_id,
        )


__all__ = ["SummarizeConversationService"]
