"""Caso de uso para gerar uma resposta de IA para uma conversa."""

import app.services.groq_service as legacy


class AnswerConversationService:
    def __init__(self, ai_gateway=None):
        self.ai_gateway = ai_gateway or legacy.GroqService()

    def execute(
        self,
        conversation,
        *,
        through_message_id: int | None = None,
        history: list[dict[str, str]] | None = None,
        inbound_batch: tuple[int, ...] = (),
    ):
        context = {"inbound_batch": inbound_batch} if inbound_batch else {}
        if history is not None:
            return self.ai_gateway.answer_conversation(conversation, history=history, **context)
        return self.ai_gateway.answer_conversation(
            conversation,
            through_message_id=through_message_id,
            **context,
        )


__all__ = ["AnswerConversationService"]
