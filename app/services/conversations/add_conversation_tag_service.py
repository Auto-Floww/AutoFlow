"""Use case for attaching a tag to a conversation."""

import app.services.conversation_service as legacy


class AddConversationTagService:
    def execute(
        self,
        company_id: int,
        conversation_id: int,
        tag_id: int,
        *,
        commit: bool = True,
    ):
        return legacy.ConversationService.add_tag(
            company_id,
            conversation_id,
            tag_id,
            commit=commit,
        )


__all__ = ["AddConversationTagService"]
