"""Use case for generating an AI answer for one conversation."""

import app.services.groq_service as legacy


class AnswerConversationService:
    def __init__(self, ai_gateway=None):
        self.ai_gateway = ai_gateway or legacy.GroqService()

    def execute(self, conversation, *, through_message_id: int | None = None):
        return self.ai_gateway.answer_conversation(
            conversation,
            through_message_id=through_message_id,
        )


__all__ = ["AnswerConversationService"]
