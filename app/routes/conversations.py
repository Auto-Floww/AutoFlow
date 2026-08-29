"""Conversation Blueprint wiring and compatibility handler exports."""

from app.controllers.conversations_controller import ConversationsController, bp

index = ConversationsController.index
detail = ConversationsController.detail
create = ConversationsController.create
assume = ConversationsController.assume
return_to_ai = ConversationsController.return_to_ai
resolve = ConversationsController.resolve
send_message = ConversationsController.send_message
add_tag = ConversationsController.add_tag
remove_tag = ConversationsController.remove_tag

__all__ = [
    "ConversationsController",
    "add_tag",
    "assume",
    "bp",
    "create",
    "detail",
    "index",
    "remove_tag",
    "resolve",
    "return_to_ai",
    "send_message",
]
