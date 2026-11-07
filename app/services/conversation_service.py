"""Ciclo de vida das conversas, idempotência das mensagens, transferência para atendimento humano e memória."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import CompanyMember, Conversation, ConversationTag, Customer, Message, Tag
from app.models.base import utcnow
from app.services.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.services.tenancy import ensure_same_company, tenant_get


GROQ_OUTBOUND_STATUSES = ("SENT", "DELIVERED", "READ")
HANDOFF_CONFIRMATION = "Vou encaminhar você para um atendente humano. Por favor, aguarde um momento."
HANDOFF_CONFIRMATION_KEY = "ai-handoff-confirmation:"


class ConversationOperations:
    @staticmethod
    def get(company_id: int, conversation_id: int, *, lock: bool = False) -> Conversation:
        return tenant_get(Conversation, company_id, conversation_id, lock=lock)

    @staticmethod
    def get_or_create(
        company_id: int,
        *,
        customer_id: int,
        channel: str = "WHATSAPP",
        external_id: str | None = None,
        whatsapp_integration_id: int | None = None,
        commit: bool = True,
    ) -> tuple[Conversation, bool]:
        # A linha estável do cliente serializa o check/create de conversa ativa.
        # A unique com external_id não ajuda no WhatsApp, onde esse valor é NULL.
        customer = tenant_get(Customer, company_id, customer_id, lock=True)
        channel = channel.upper()
        query = Conversation.query.filter_by(
            company_id=int(company_id), customer_id=customer.id, channel=channel
        ).filter(Conversation.status.in_(("OPEN", "PENDING")))
        if external_id:
            external_match = Conversation.query.filter_by(
                company_id=int(company_id), channel=channel, external_id=external_id
            ).one_or_none()
            if external_match:
                ensure_same_company(company_id, customer, external_match)
                return external_match, False
        conversation = query.order_by(Conversation.created_at.desc()).first()
        created = False
        if conversation is None:
            conversation = Conversation(
                company_id=int(company_id),
                customer_id=customer.id,
                channel=channel,
                external_id=external_id,
                whatsapp_integration_id=whatsapp_integration_id,
                status="OPEN",
                ai_status="ACTIVE",
            )
            db.session.add(conversation)
            created = True
        elif whatsapp_integration_id and not conversation.whatsapp_integration_id:
            conversation.whatsapp_integration_id = whatsapp_integration_id
        try:
            db.session.flush()
            if commit:
                db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if external_id:
                conversation = Conversation.query.filter_by(
                    company_id=int(company_id), channel=channel, external_id=external_id
                ).one()
                created = False
            else:
                raise
        return conversation, created

    @staticmethod
    def record_inbound(
        company_id: int,
        *,
        conversation_id: int,
        content: str,
        external_message_id: str,
        message_type: str = "TEXT",
        payload: dict | None = None,
        commit: bool = True,
    ) -> tuple[Message, bool]:
        if not external_message_id:
            raise ValidationError("External message ID is required for webhook idempotency")
        existing = Message.query.filter_by(
            company_id=int(company_id), external_message_id=external_message_id
        ).one_or_none()
        if existing:
            return existing, False
        conversation = tenant_get(Conversation, company_id, conversation_id, lock=True)
        message = Message(
            company_id=int(company_id),
            conversation_id=conversation.id,
            customer_id=conversation.customer_id,
            external_message_id=external_message_id,
            direction="INBOUND",
            sender_type="CUSTOMER",
            message_type=message_type.upper(),
            content=content or "",
            payload_json=payload or {},
            status="RECEIVED",
            processing_status="PENDING",
        )
        now = utcnow()
        conversation.last_message_at = now
        conversation.unread_count += 1
        conversation.status = "OPEN"
        conversation.customer.last_interaction_at = now
        db.session.add(message)
        try:
            db.session.flush()
            if commit:
                db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing = Message.query.filter_by(
                company_id=int(company_id), external_message_id=external_message_id
            ).one_or_none()
            if existing:
                return existing, False
            raise
        return message, True

    @staticmethod
    def record_outbound(
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
    ) -> Message:
        if idempotency_key:
            existing = Message.query.filter_by(
                company_id=int(company_id), idempotency_key=idempotency_key
            ).one_or_none()
            if existing:
                return existing
        conversation = tenant_get(Conversation, company_id, conversation_id, lock=True)
        sender_type = sender_type.upper()
        if sender_type not in {"AI", "AGENT", "SYSTEM"}:
            raise ValidationError("Invalid outbound sender type")
        if sender_type == "AGENT" and not sender_user_id:
            raise ValidationError("An agent message requires sender_user_id")
        if sender_type == "AGENT":
            if conversation.ai_status == "ACTIVE":
                raise ConflictError("Claim the conversation before sending as an agent")
            if conversation.assigned_user_id != sender_user_id:
                raise AuthorizationError(
                    "Only the assigned agent can send messages in this conversation"
                )
        if reply_to_id:
            reply = tenant_get(Message, company_id, reply_to_id)
            if reply.conversation_id != conversation.id:
                raise ValidationError("Reply message belongs to a different conversation")
        message = Message(
            company_id=int(company_id),
            conversation_id=conversation.id,
            customer_id=conversation.customer_id,
            sender_user_id=sender_user_id,
            reply_to_id=reply_to_id,
            direction="OUTBOUND",
            sender_type=sender_type,
            message_type="TEXT",
            content=(content or "").strip(),
            status="QUEUED",
            processing_status="PROCESSED",
            ai_metadata_json=ai_metadata or {},
            idempotency_key=idempotency_key,
        )
        if not message.content:
            raise ValidationError("Message content cannot be empty")
        conversation.last_message_at = utcnow()
        db.session.add(message)
        try:
            db.session.flush()
            if commit:
                db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if idempotency_key:
                existing = Message.query.filter_by(
                    company_id=int(company_id), idempotency_key=idempotency_key
                ).one_or_none()
                if existing:
                    return existing
            raise
        return message

    @staticmethod
    def claim(
        company_id: int,
        conversation_id: int,
        *,
        user_id: int,
        commit: bool = True,
    ) -> Conversation:
        membership = CompanyMember.query.filter_by(
            company_id=int(company_id), user_id=user_id, status="ACTIVE"
        ).one_or_none()
        if membership is None:
            raise AuthorizationError("Agent does not belong to this company")
        conversation = tenant_get(Conversation, company_id, conversation_id, lock=True)
        if conversation.assigned_user_id not in {None, user_id}:
            raise ConflictError("Conversation is already assigned to another agent")
        conversation.assigned_user_id = user_id
        conversation.ai_status = "PAUSED"
        conversation.human_requested = False
        conversation.status = "OPEN"
        if commit:
            db.session.commit()
        return conversation

    @staticmethod
    def transfer_to_human(
        company_id: int,
        conversation_id: int,
        *,
        reason: str | None = None,
        commit: bool = True,
    ) -> Conversation:
        conversation = tenant_get(Conversation, company_id, conversation_id, lock=True)
        db.session.refresh(conversation, with_for_update=True)
        new_handoff = not conversation.human_requested
        conversation.ai_status = "PAUSED"
        conversation.human_requested = True
        conversation.status = "PENDING"
        memory = dict(conversation.memory_json or {})
        memory["handoff_reason"] = (reason or "Cliente solicitou atendimento humano")[:500]
        memory["handoff_at"] = utcnow().isoformat()
        if new_handoff:
            memory["handoff_sequence"] = int(memory.get("handoff_sequence") or 0) + 1
            memory.pop("handoff_confirmation_id", None)
        conversation.memory_json = memory
        if new_handoff:
            from app.services.notification_service import NotificationOperations

            NotificationOperations.create(
                company_id,
                notification_type="HUMAN_REQUESTED",
                title="Cliente solicitou atendimento humano",
                body=f"{conversation.customer.name} aguarda um agente.",
                link_url=f"/conversations?conversation={conversation.id}",
                data={"conversation_id": conversation.id, "reason": reason},
                idempotency_key=(
                    f"handoff:{conversation.id}:{memory['handoff_sequence']}"
                ),
                commit=False,
            )
        if commit:
            db.session.commit()
        return conversation

    @staticmethod
    def transfer_from_ai(
        company_id: int,
        conversation_id: int,
        *,
        reason: str | None,
        inbound_batch: tuple[int, ...],
    ) -> tuple[Conversation, int | None]:
        from app.services.outbox import EnqueueOutboxTaskService

        # The processing worker also locks inbound messages before the conversation.
        inbound_messages = []
        if inbound_batch:
            inbound_messages = (
                Message.query.filter(
                    Message.company_id == company_id,
                    Message.conversation_id == conversation_id,
                    Message.direction == "INBOUND",
                    Message.id.in_(inbound_batch),
                    Message.processing_status.in_(("PENDING", "PROCESSING")),
                )
                .order_by(Message.id)
                .populate_existing()
                .with_for_update()
                .all()
            )
        conversation = Conversation.query.filter_by(
            company_id=company_id, id=conversation_id
        ).populate_existing().with_for_update().one_or_none()
        if conversation is None:
            raise NotFoundError("Conversation not found")
        memory = conversation.memory_json or {}
        if conversation.ai_status != "ACTIVE" or conversation.human_requested:
            if not inbound_batch and memory.get("handoff_confirmation_id"):
                db.session.commit()
                return conversation, None
            raise ConflictError("AI is paused for this conversation")
        if inbound_batch and (
            memory.get("processing_message_id") != inbound_batch[0]
            or all(message.id != inbound_batch[0] for message in inbound_messages)
        ):
            raise ConflictError("The AI no longer owns this inbound message")

        ConversationOperations.transfer_to_human(
            company_id, conversation_id, reason=reason, commit=False
        )
        outbox_id = None
        if conversation.channel == "WHATSAPP":
            sequence = conversation.memory_json["handoff_sequence"]
            outbound = ConversationOperations.record_outbound(
                company_id,
                conversation_id=conversation.id,
                content=HANDOFF_CONFIRMATION,
                reply_to_id=max(inbound_batch, default=None),
                idempotency_key=f"{HANDOFF_CONFIRMATION_KEY}{conversation.id}:{sequence}",
                commit=False,
            )
            outbox_id = EnqueueOutboxTaskService().execute(
                "send_whatsapp_message",
                {"message_id": outbound.id},
                idempotency_key=f"send-whatsapp-message:{outbound.id}",
                company_id=company_id,
            ).id
            memory = dict(conversation.memory_json or {})
            memory["handoff_confirmation_id"] = outbound.id
            conversation.memory_json = memory
        processed_at = utcnow()
        for message in inbound_messages:
            message.processing_status = "PROCESSED"
            message.processed_at = processed_at
            message.error_message = None
        if inbound_batch:
            memory = dict(conversation.memory_json or {})
            memory.pop("processing_message_id", None)
            memory.pop("processing_started_at", None)
            conversation.memory_json = memory
        db.session.commit()
        return conversation, outbox_id

    @staticmethod
    def return_to_ai(
        company_id: int,
        conversation_id: int,
        *,
        user_id: int | None = None,
        commit: bool = True,
    ) -> Conversation:
        conversation = tenant_get(Conversation, company_id, conversation_id, lock=True)
        db.session.refresh(conversation, with_for_update=True)
        if user_id and conversation.assigned_user_id not in {None, user_id}:
            raise AuthorizationError("Only the assigned agent can return this conversation")
        conversation.assigned_user_id = None
        conversation.human_requested = False
        conversation.ai_status = "ACTIVE"
        conversation.status = "OPEN"
        if (conversation.memory_json or {}).get("handoff_confirmation_id"):
            memory = dict(conversation.memory_json)
            memory.pop("handoff_confirmation_id")
            conversation.memory_json = memory
        if commit:
            db.session.commit()
        return conversation

    @staticmethod
    def mark_read(
        company_id: int, conversation_id: int, *, commit: bool = True
    ) -> Conversation:
        conversation = tenant_get(Conversation, company_id, conversation_id, lock=True)
        conversation.unread_count = 0
        if commit:
            db.session.commit()
        return conversation

    @staticmethod
    def recent_messages(
        company_id: int,
        conversation_id: int,
        *,
        limit: int = 30,
        through_message_id: int | None = None,
        for_groq: bool = False,
    ) -> list[Message]:
        conversation = tenant_get(Conversation, company_id, conversation_id)
        query = Message.query.filter_by(
            company_id=int(company_id), conversation_id=conversation.id
        )
        if through_message_id is not None:
            query = query.filter(Message.id <= int(through_message_id))
        if for_groq:
            query = query.filter(
                Message.content != "",
                db.or_(
                    Message.direction == "INBOUND",
                    db.and_(
                        Message.direction == "OUTBOUND",
                        Message.sender_type.in_(("AI", "AGENT")),
                        Message.status.in_(GROQ_OUTBOUND_STATUSES),
                    ),
                ),
            )
        rows = query.order_by(Message.created_at.desc(), Message.id.desc()).limit(
            min(max(int(limit), 1), 100)
        ).all()
        return list(reversed(rows))

    @staticmethod
    def groq_history(
        company_id: int,
        conversation_id: int,
        *,
        limit: int = 30,
        through_message_id: int | None = None,
    ) -> list[dict[str, str]]:
        return ConversationOperations.format_groq_history(
            ConversationOperations.recent_messages(
                company_id,
                conversation_id,
                limit=limit,
                through_message_id=through_message_id,
                for_groq=True,
            )
        )

    @staticmethod
    def format_groq_history(messages: list[Message]) -> list[dict[str, str]]:
        history: list[dict[str, str]] = []
        for message in messages:
            if not message.content:
                continue
            if message.direction == "INBOUND":
                role = "user"
            elif (
                message.direction == "OUTBOUND"
                and message.sender_type in {"AI", "AGENT"}
                and message.status in GROQ_OUTBOUND_STATUSES
            ):
                role = "assistant"
            else:
                continue
            history.append({"role": role, "content": message.content})
        return history

    @staticmethod
    def groq_history_range(
        company_id: int,
        conversation_id: int,
        *,
        after_message_id: int = 0,
        through_message_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, str]]:
        return ConversationOperations.format_groq_history(
            ConversationOperations.summary_message_range(
                company_id,
                conversation_id,
                after_message_id=after_message_id,
                through_message_id=through_message_id,
                limit=limit,
            )
        )

    @staticmethod
    def summary_message_range(
        company_id: int,
        conversation_id: int,
        *,
        after_message_id: int = 0,
        through_message_id: int | None = None,
        limit: int = 100,
    ) -> list[Message]:
        tenant_get(Conversation, company_id, conversation_id)
        query = Message.query.filter(
            Message.company_id == int(company_id),
            Message.conversation_id == conversation_id,
            Message.id > int(after_message_id),
        )
        if through_message_id is not None:
            query = query.filter(Message.id <= int(through_message_id))
        return query.order_by(Message.id).limit(min(max(int(limit), 1), 200)).all()

    @staticmethod
    def set_summary(
        company_id: int,
        conversation_id: int,
        *,
        summary: str,
        summarized_through_message_id: int | None = None,
        expected_cursor: int | None = None,
        commit: bool = True,
    ) -> Conversation:
        conversation = tenant_get(Conversation, company_id, conversation_id, lock=True)
        if expected_cursor is not None:
            # The identity map may still contain the snapshot used by Groq.
            db.session.refresh(conversation, with_for_update=True)
        memory = dict(conversation.memory_json or {})
        previous_cursor = int(memory.get("summarized_through_message_id") or 0)
        if expected_cursor is not None and previous_cursor != expected_cursor:
            raise ConflictError("Conversation summary cursor changed")
        cursor = int(summarized_through_message_id or 0)
        if cursor and cursor < previous_cursor:
            return conversation
        conversation.summary = summary.strip()
        if cursor:
            memory["summarized_through_message_id"] = cursor
        memory["summary_updated_at"] = utcnow().isoformat()
        conversation.memory_json = memory
        if commit:
            db.session.commit()
        return conversation

    @staticmethod
    def add_tag(
        company_id: int,
        conversation_id: int,
        tag_id: int,
        *,
        commit: bool = True,
    ) -> Tag:
        conversation = tenant_get(Conversation, company_id, conversation_id)
        tag = tenant_get(Tag, company_id, tag_id)
        ensure_same_company(company_id, conversation, tag)
        existing = ConversationTag.query.filter_by(
            company_id=int(company_id), conversation_id=conversation.id, tag_id=tag.id
        ).one_or_none()
        if existing is None:
            db.session.add(
                ConversationTag(
                    company_id=int(company_id), conversation_id=conversation.id, tag_id=tag.id
                )
            )
        if commit:
            db.session.commit()
        return tag

    @staticmethod
    def update_message_status(
        company_id: int,
        external_message_id: str,
        status: str,
        *,
        timestamp=None,
        error_message: str | None = None,
        commit: bool = True,
    ) -> Message | None:
        message = Message.query.filter_by(
            company_id=int(company_id), external_message_id=external_message_id
        ).one_or_none()
        if message is None:
            return None
        status = status.upper()
        allowed = {"SENT", "DELIVERED", "READ", "FAILED"}
        if status not in allowed:
            raise ValidationError("Invalid message status")
        message.status = status
        occurred_at = timestamp or utcnow()
        if status == "SENT":
            message.sent_at = occurred_at
        elif status == "DELIVERED":
            message.delivered_at = occurred_at
        elif status == "READ":
            message.read_at = occurred_at
        elif status == "FAILED":
            message.error_message = error_message
        if commit:
            db.session.commit()
        return message


# Backwards-compatible alias; use-case Services live in ``app.services.conversations``.
ConversationService = ConversationOperations
transfer_to_human = ConversationOperations.transfer_to_human
