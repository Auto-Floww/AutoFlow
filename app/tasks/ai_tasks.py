"""Celery tasks for the WhatsApp -> Groq -> WhatsApp pipeline."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

from celery import shared_task
from flask import current_app

from app.extensions import db
from app.models import AISettings, Appointment, Conversation, Message, User
from app.models.base import utcnow
from app.security import decrypt_secret
from app.services.ai import AnswerConversationService, SummarizeConversationService
from app.services.auth import SendPasswordResetEmailService
from app.services.conversations import (
    RecordOutboundMessageService,
    SetConversationSummaryService,
)
from app.services.exceptions import DomainError, ExternalServiceError
from app.services.notifications import CreateNotificationService
from app.services.outbox import (
    DispatchOutboxBestEffortService,
    DispatchPendingOutboxService,
    EnqueueOutboxTaskService,
)
from app.services.tenancy import tenant_get
from app.services.whatsapp import SendWhatsAppTextService


PROCESSING_LEASE = timedelta(minutes=5)
SEND_LEASE = timedelta(minutes=1)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _evolution_message_id(result: dict) -> str | None:
    """Normalize Evolution v2 and legacy provider send responses."""

    key = result.get("key") or {}
    if isinstance(key, dict) and key.get("id"):
        return str(key["id"])
    if result.get("id"):
        return str(result["id"])
    messages = result.get("messages") or []
    if messages and isinstance(messages[0], dict) and messages[0].get("id"):
        return str(messages[0]["id"])
    return None


def _claim_conversation(conversation: Conversation, message_id: int) -> bool:
    memory = dict(conversation.memory_json or {})
    holder = memory.get("processing_message_id")
    started = _parse_timestamp(memory.get("processing_started_at"))
    lease_active = started is not None and utcnow() - started < PROCESSING_LEASE
    if holder and int(holder) != message_id and lease_active:
        return False
    memory["processing_message_id"] = message_id
    memory["processing_started_at"] = utcnow().isoformat()
    conversation.memory_json = memory
    return True


def _release_conversation(conversation_id: int, message_id: int) -> None:
    conversation = Conversation.query.filter_by(id=conversation_id).with_for_update().one_or_none()
    if conversation is None:
        return
    memory = dict(conversation.memory_json or {})
    if int(memory.get("processing_message_id") or 0) == message_id:
        memory.pop("processing_message_id", None)
        memory.pop("processing_started_at", None)
        conversation.memory_json = memory


@shared_task(
    bind=True,
    name="app.tasks.process_message",
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_message(self, message_id: int) -> dict:
    """Generate exactly one AI reply for a committed inbound message."""

    message = Message.query.filter_by(id=int(message_id)).with_for_update().one_or_none()
    if message is None:
        return {"status": "missing", "message_id": message_id}
    if message.direction != "INBOUND":
        return {"status": "ignored", "message_id": message.id}
    if message.processing_status in {"PROCESSED", "SKIPPED"}:
        return {"status": message.processing_status.lower(), "message_id": message.id}
    if message.processing_status == "PROCESSING":
        processing_started = _parse_timestamp(
            (message.ai_metadata_json or {}).get("processing_started_at")
        )
        if processing_started and utcnow() - processing_started < PROCESSING_LEASE:
            db.session.rollback()
            raise self.retry(countdown=3, max_retries=20)
    company_id = message.company_id
    conversation = Conversation.query.filter_by(
        id=message.conversation_id, company_id=company_id
    ).with_for_update().one()
    if conversation.ai_status != "ACTIVE" or conversation.human_requested:
        message.processing_status = "SKIPPED"
        message.processed_at = utcnow()
        db.session.commit()
        return {"status": "ai_paused", "message_id": message.id}
    if not _claim_conversation(conversation, message.id):
        db.session.rollback()
        raise self.retry(countdown=2, max_retries=20)
    message.processing_status = "PROCESSING"
    metadata = dict(message.ai_metadata_json or {})
    metadata["processing_started_at"] = utcnow().isoformat()
    message.ai_metadata_json = metadata
    db.session.commit()

    try:
        # Reload after releasing the transaction; network calls never hold DB locks.
        conversation = Conversation.query.filter_by(
            id=message.conversation_id, company_id=company_id
        ).one()
        # Coalesce messages that arrived before this Groq request starts. This keeps
        # rapid consecutive WhatsApp messages in one answer and makes their tasks
        # idempotently observe PROCESSED afterwards.
        batch_tail = (
            Message.query.filter(
                Message.company_id == company_id,
                Message.conversation_id == conversation.id,
                Message.direction == "INBOUND",
                Message.processing_status.in_(("PENDING", "PROCESSING")),
            )
            .order_by(Message.id.desc())
            .first()
        )
        through_message_id = max(message.id, batch_tail.id if batch_tail else message.id)
        answer, ai_metadata = AnswerConversationService().execute(
            conversation, through_message_id=through_message_id
        )

        # A human may have claimed the chat while Groq was processing.
        conversation = Conversation.query.filter_by(
            id=message.conversation_id, company_id=company_id
        ).with_for_update().one()
        inbound = Message.query.filter_by(
            id=message.id, company_id=company_id
        ).with_for_update().one()
        if conversation.ai_status != "ACTIVE" or conversation.human_requested:
            inbound.processing_status = "SKIPPED"
            inbound.processed_at = utcnow()
            _release_conversation(conversation.id, inbound.id)
            db.session.commit()
            return {"status": "ai_paused_before_persist", "message_id": inbound.id}
        outbound = RecordOutboundMessageService().execute(
            company_id,
            conversation_id=conversation.id,
            content=answer,
            sender_type="AI",
            reply_to_id=through_message_id,
            ai_metadata=ai_metadata,
            idempotency_key=f"ai-reply:{through_message_id}",
            commit=False,
        )
        batched_messages = Message.query.filter(
            Message.company_id == company_id,
            Message.conversation_id == conversation.id,
            Message.direction == "INBOUND",
            Message.id <= through_message_id,
            Message.processing_status.in_(("PENDING", "PROCESSING")),
        ).with_for_update().all()
        processed_at = utcnow()
        for batched in batched_messages:
            batched.processing_status = "PROCESSED"
            batched.processed_at = processed_at
        _release_conversation(conversation.id, inbound.id)
        send_outbox = EnqueueOutboxTaskService().execute(
            "send_whatsapp_message",
            {"message_id": outbound.id},
            idempotency_key=f"send-whatsapp-message:{outbound.id}",
            company_id=company_id,
        )
        settings = AISettings.query.filter_by(company_id=company_id).one_or_none()
        threshold = settings.summary_threshold if settings else 60
        summary_cursor = int(
            (conversation.memory_json or {}).get("summarized_through_message_id") or 0
        )
        unsummarized_count = Message.query.filter(
            Message.company_id == company_id,
            Message.conversation_id == conversation.id,
            Message.id > summary_cursor,
        ).count()
        summary_outbox = None
        if unsummarized_count >= threshold:
            summary_outbox = EnqueueOutboxTaskService().execute(
                "generate_summary",
                {"conversation_id": conversation.id},
                idempotency_key=(
                    f"generate-summary:{conversation.id}:{through_message_id}"
                ),
                company_id=company_id,
            )
        db.session.commit()
        DispatchOutboxBestEffortService().execute(send_outbox.id)
        if summary_outbox is not None:
            DispatchOutboxBestEffortService().execute(summary_outbox.id)
        return {
            "status": "processed",
            "message_id": inbound.id,
            "outbound_message_id": outbound.id,
            "batched_message_ids": [item.id for item in batched_messages],
            "outbox_id": send_outbox.id,
        }
    except ExternalServiceError as exc:
        db.session.rollback()
        failed = Message.query.filter_by(id=message_id, company_id=company_id).one_or_none()
        if failed:
            failed.processing_status = "PENDING" if exc.retryable else "FAILED"
            failed.error_message = exc.message
            _release_conversation(failed.conversation_id, failed.id)
            db.session.commit()
        if exc.retryable:
            raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)))
        raise
    except DomainError as exc:
        db.session.rollback()
        failed = Message.query.filter_by(id=message_id, company_id=company_id).one_or_none()
        paused = False
        if failed:
            conversation = Conversation.query.filter_by(
                id=failed.conversation_id, company_id=company_id
            ).one_or_none()
            paused = bool(
                conversation
                and (
                    conversation.ai_status != "ACTIVE"
                    or conversation.human_requested
                )
            )
            failed.processing_status = "SKIPPED" if paused else "FAILED"
            failed.error_message = None if paused else exc.message
            failed.processed_at = utcnow()
            _release_conversation(failed.conversation_id, failed.id)
            db.session.commit()
        if paused:
            return {"status": "ai_paused", "message_id": message_id}
        raise
    except Exception:
        db.session.rollback()
        failed = Message.query.filter_by(id=message_id, company_id=company_id).one_or_none()
        if failed:
            failed.processing_status = "FAILED"
            _release_conversation(failed.conversation_id, failed.id)
            db.session.commit()
        raise


@shared_task(
    bind=True,
    name="app.tasks.send_whatsapp_message",
    max_retries=12,
    acks_late=True,
    reject_on_worker_lost=True,
)
def send_whatsapp_message(self, message_id: int) -> dict:
    message = Message.query.filter_by(id=int(message_id)).with_for_update().one_or_none()
    if message is None:
        return {"status": "missing", "message_id": message_id}
    if message.direction != "OUTBOUND":
        return {"status": "ignored", "message_id": message.id}
    if message.external_message_id and message.status in {"SENT", "DELIVERED", "READ"}:
        return {
            "status": message.status.lower(),
            "message_id": message.id,
            "external_message_id": message.external_message_id,
        }
    # Older workers only understood Meta's ``messages[0].id`` response. An
    # Evolution v2 send may therefore have reached WhatsApp even though the old
    # worker recorded this parser error. Never resend such an ambiguous result.
    if message.error_message in {
        "WhatsApp returned no message identifier",
        "delivery outcome unknown after provider response; verify WhatsApp before retry",
    }:
        if message.status != "FAILED":
            message.status = "FAILED"
            message.error_message = (
                "delivery outcome unknown after provider response; "
                "verify WhatsApp before retry"
            )
            db.session.commit()
        return {"status": "delivery_unknown", "message_id": message.id}
    send_metadata = dict(message.ai_metadata_json or {})
    send_started = _parse_timestamp(send_metadata.get("whatsapp_send_started_at"))
    if message.status == "SENDING":
        if send_started is not None and utcnow() - send_started < SEND_LEASE:
            remaining = max(
                2,
                int((SEND_LEASE - (utcnow() - send_started)).total_seconds()),
            )
            db.session.rollback()
            raise self.retry(countdown=min(15, remaining), max_retries=12)
        # A worker may have reached Meta and crashed before persisting the response.
        # Re-sending here could duplicate a real customer message, so reconciliation
        # or an explicit manual retry is required.
        message.status = "FAILED"
        message.error_message = "delivery outcome unknown"
        send_metadata.pop("whatsapp_send_started_at", None)
        message.ai_metadata_json = send_metadata
        db.session.commit()
        return {"status": "delivery_unknown", "message_id": message.id}
    conversation = tenant_get(
        Conversation, message.company_id, message.conversation_id, lock=True
    )
    # Last-moment handoff guard prevents a queued AI reply racing a human agent.
    if message.sender_type == "AI" and (
        conversation.ai_status != "ACTIVE" or conversation.human_requested
    ):
        message.status = "FAILED"
        message.processing_status = "SKIPPED"
        message.error_message = "AI paused before WhatsApp delivery"
        db.session.commit()
        return {"status": "ai_paused", "message_id": message.id}
    customer = conversation.customer
    integration_id = conversation.whatsapp_integration_id
    company_id = message.company_id
    content = message.content
    phone = customer.phone_normalized
    message.status = "SENDING"
    send_metadata["whatsapp_send_started_at"] = utcnow().isoformat()
    message.ai_metadata_json = send_metadata
    db.session.commit()
    try:
        result = SendWhatsAppTextService().execute(
            company_id,
            to=phone,
            text=content,
            integration_id=integration_id,
        )
        external_id = _evolution_message_id(result)
        if not external_id:
            raise ExternalServiceError(
                "WhatsApp returned no message identifier", retryable=True
            )
        message = Message.query.filter_by(id=message_id, company_id=company_id).one()
        message.external_message_id = external_id
        message.status = "SENT"
        message.sent_at = utcnow()
        message.error_message = None
        metadata = dict(message.ai_metadata_json or {})
        metadata.pop("whatsapp_send_started_at", None)
        message.ai_metadata_json = metadata
        db.session.commit()
        return {
            "status": "sent",
            "message_id": message.id,
            "external_message_id": external_id,
        }
    except ExternalServiceError as exc:
        db.session.rollback()
        message = Message.query.filter_by(id=message_id, company_id=company_id).one_or_none()
        if message:
            message.status = "QUEUED" if exc.retryable else "FAILED"
            message.error_message = exc.message
            metadata = dict(message.ai_metadata_json or {})
            metadata.pop("whatsapp_send_started_at", None)
            message.ai_metadata_json = metadata
            db.session.commit()
        if exc.retryable:
            raise self.retry(exc=exc, countdown=min(300, 2 ** (self.request.retries + 2)))
        raise
    except DomainError as exc:
        db.session.rollback()
        message = Message.query.filter_by(id=message_id, company_id=company_id).one_or_none()
        if message:
            message.status = "FAILED"
            message.error_message = exc.message
            metadata = dict(message.ai_metadata_json or {})
            metadata.pop("whatsapp_send_started_at", None)
            message.ai_metadata_json = metadata
            db.session.commit()
        raise


@shared_task(
    bind=True,
    name="app.tasks.generate_summary",
    max_retries=4,
    acks_late=True,
)
def generate_summary(self, conversation_id: int) -> dict:
    conversation = Conversation.query.filter_by(id=int(conversation_id)).one_or_none()
    if conversation is None:
        return {"status": "missing", "conversation_id": conversation_id}
    company_id = conversation.company_id
    previous_cursor = int((conversation.memory_json or {}).get("summarized_through_message_id") or 0)
    batch = (
        Message.query.filter(
            Message.company_id == company_id,
            Message.conversation_id == conversation.id,
            Message.id > previous_cursor,
        )
        .order_by(Message.id)
        .limit(100)
        .all()
    )
    if not batch:
        return {"status": "current", "conversation_id": conversation.id}
    cursor = batch[-1].id
    try:
        summary = SummarizeConversationService().execute(
            conversation,
            after_message_id=previous_cursor,
            through_message_id=cursor,
        )
        SetConversationSummaryService().execute(
            company_id,
            conversation.id,
            summary=summary,
            summarized_through_message_id=cursor,
        )
        return {"status": "summarized", "conversation_id": conversation.id, "cursor": cursor}
    except ExternalServiceError as exc:
        if exc.retryable:
            raise self.retry(exc=exc, countdown=min(120, 2 ** (self.request.retries + 2)))
        raise


@shared_task(
    bind=True,
    name="app.tasks.password_reset_email",
    max_retries=5,
    acks_late=True,
)
def password_reset_email(
    self,
    user_id: int | None = None,
    reset_token_encrypted: str | None = None,
) -> dict:
    """Send a reset link without exposing the plaintext token to the broker or logs."""

    # Unknown addresses deliberately produce an empty outbox payload and execute
    # this same task path. It must remain a side-effect-free success.
    if user_id is None or not reset_token_encrypted:
        return SendPasswordResetEmailService().execute(None, None)

    user = db.session.get(User, int(user_id))
    if user is None or not user.is_active:
        return {"status": "noop"}
    try:
        token = decrypt_secret(reset_token_encrypted)
    except RuntimeError as exc:
        raise ExternalServiceError(
            "Password reset token could not be decrypted",
            retryable=False,
        ) from exc
    if not token:
        return {"status": "stale", "user_id": user.id}

    digest = hashlib.sha256(token.encode()).hexdigest()
    token_is_current = bool(
        user.reset_token_hash
        and user.reset_token_expires_at
        and user.reset_token_expires_at >= utcnow()
        and hmac.compare_digest(user.reset_token_hash, digest)
    )
    if not token_is_current:
        return {"status": "stale", "user_id": user.id}

    app_url = str(current_app.config["APP_URL"]).rstrip("/") + "/"
    reset_url = urljoin(app_url, f"reset-password/{quote(token, safe='')}")
    try:
        result = SendPasswordResetEmailService().execute(user.email, reset_url)
    except ExternalServiceError as exc:
        if exc.retryable:
            raise self.retry(
                exc=exc,
                countdown=min(300, 2 ** (self.request.retries + 2)),
            )
        raise
    return {"status": result["status"], "user_id": user.id}


@shared_task(name="app.tasks.dispatch_task_outbox", acks_late=True)
def dispatch_task_outbox(limit: int | None = None) -> dict[str, int]:
    """Celery beat entrypoint that republishes due transactional outbox rows."""

    return DispatchPendingOutboxService().execute(limit=limit)


@shared_task(name="app.tasks.send_notification", acks_late=True)
def send_notification(
    company_id: int,
    notification_type: str,
    title: str,
    body: str | None = None,
    user_id: int | None = None,
    link_url: str | None = None,
    data: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    rows = CreateNotificationService().execute(
        company_id,
        notification_type=notification_type,
        title=title,
        body=body,
        user_id=user_id,
        link_url=link_url,
        data=data,
        idempotency_key=idempotency_key,
    )
    return {"status": "created", "notification_ids": [row.id for row in rows]}


@shared_task(name="app.tasks.process_appointment", acks_late=True)
def process_appointment(appointment_id: int, event: str = "created") -> dict:
    appointment = Appointment.query.filter_by(id=int(appointment_id)).one_or_none()
    if appointment is None:
        return {"status": "missing", "appointment_id": appointment_id}
    event = event.lower()
    titles = {
        "created": "Novo agendamento",
        "cancelled": "Agendamento cancelado",
        "reminder": "Lembrete de agendamento",
    }
    title = titles.get(event, "Agendamento atualizado")
    notifications = CreateNotificationService().execute(
        appointment.company_id,
        notification_type=f"APPOINTMENT_{event.upper()}",
        title=title,
        body=(
            f"{appointment.customer.name} — {appointment.service.name} — "
            f"{appointment.starts_at.isoformat()}"
        ),
        link_url=f"/appointments/{appointment.id}",
        data={"appointment_id": appointment.id, "status": appointment.status},
        idempotency_key=f"appointment:{appointment.id}:{event}",
    )
    return {
        "status": "processed",
        "appointment_id": appointment.id,
        "notification_ids": [row.id for row in notifications],
    }
