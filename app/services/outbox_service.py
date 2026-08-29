"""Durable dispatch of allow-listed Celery tasks through a transactional outbox."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from flask import current_app

from app.extensions import db
from app.models import TaskOutbox
from app.models.base import utcnow
from app.models.outbox import OUTBOX_TASK_NAMES
from app.services.exceptions import ValidationError


TASK_PAYLOAD_KEYS = {
    "process_message": {"message_id"},
    "send_whatsapp_message": {"message_id"},
    "generate_summary": {"conversation_id"},
    "password_reset_email": {"user_id", "reset_token_encrypted"},
    "process_appointment": {"appointment_id", "event"},
    "send_notification": {
        "company_id",
        "notification_type",
        "title",
        "body",
        "user_id",
        "link_url",
        "data",
        "idempotency_key",
    },
}


class OutboxDispatcher:
    """Persist task intent first; broker delivery is a recoverable second step."""

    @staticmethod
    def enqueue(
        task_name: str,
        payload: dict[str, Any] | None,
        *,
        idempotency_key: str,
        company_id: int | None = None,
        available_at=None,
    ) -> TaskOutbox:
        task_name = str(task_name or "").strip()
        if task_name not in OUTBOX_TASK_NAMES:
            raise ValidationError("Task is not allowed in the outbox")
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 190:
            raise ValidationError("A valid outbox idempotency key is required")
        task_payload = payload or {}
        if not isinstance(task_payload, dict):
            raise ValidationError("Outbox payload must be an object")
        unexpected = set(task_payload).difference(TASK_PAYLOAD_KEYS[task_name])
        if unexpected:
            raise ValidationError("Outbox payload contains unsupported fields")
        try:
            encoded = json.dumps(task_payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Outbox payload must be JSON serializable") from exc
        if len(encoded.encode("utf-8")) > 32_000:
            raise ValidationError("Outbox payload is too large")

        existing = TaskOutbox.query.filter_by(idempotency_key=key).one_or_none()
        if existing is not None:
            if existing.task_name != task_name or existing.payload_json != task_payload:
                raise ValidationError("Outbox idempotency key was reused")
            return existing

        entry = TaskOutbox(
            company_id=int(company_id) if company_id is not None else None,
            task_name=task_name,
            idempotency_key=key,
            payload_json=task_payload,
            status="PENDING",
            available_at=available_at or utcnow(),
        )
        db.session.add(entry)
        db.session.flush()
        return entry

    @staticmethod
    def _resolve_task(task_name: str):
        # Lazy import avoids a services <-> Celery task import cycle.
        from app.tasks import ai_tasks

        return {
            "process_message": ai_tasks.process_message,
            "send_whatsapp_message": ai_tasks.send_whatsapp_message,
            "generate_summary": ai_tasks.generate_summary,
            "password_reset_email": ai_tasks.password_reset_email,
            "process_appointment": ai_tasks.process_appointment,
            "send_notification": ai_tasks.send_notification,
        }[task_name]

    @staticmethod
    def dispatch_one(entry_id: int) -> bool:
        """Try one broker publish and retain a pending row on any failure."""

        entry = (
            TaskOutbox.query.filter_by(id=int(entry_id))
            .with_for_update()
            .one_or_none()
        )
        if entry is None:
            return False
        if entry.status == "DISPATCHED":
            return True
        now = utcnow()
        if entry.available_at > now:
            db.session.rollback()
            return False

        entry.attempts += 1
        entry.last_attempt_at = now
        try:
            task = OutboxDispatcher._resolve_task(entry.task_name)
            task.apply_async(
                kwargs=dict(entry.payload_json or {}),
                task_id=f"autoflow-outbox-{entry.id}",
                ignore_result=True,
                retry=False,
                retry_policy={"max_retries": 0, "interval_start": 0},
            )
        except Exception as exc:
            # Payloads may contain encrypted secrets, so neither logs nor the error
            # column include exception text or task arguments.
            entry.status = "PENDING"
            entry.error = f"{type(exc).__name__}: broker dispatch failed"
            entry.available_at = now + timedelta(
                seconds=min(300, 2 ** min(entry.attempts + 1, 8))
            )
            db.session.commit()
            current_app.logger.warning(
                "Outbox %s (%s) permanece pendente apos falha no broker",
                entry.id,
                entry.task_name,
            )
            return False

        entry.status = "DISPATCHED"
        entry.dispatched_at = utcnow()
        entry.error = None
        db.session.commit()
        return True

    @staticmethod
    def dispatch_best_effort(entry_id: int) -> bool:
        if not current_app.config.get("OUTBOX_IMMEDIATE_DISPATCH", True):
            return False
        try:
            return OutboxDispatcher.dispatch_one(entry_id)
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Falha interna ao despachar outbox %s; registro sera recuperado pelo beat",
                entry_id,
            )
            return False

    @staticmethod
    def dispatch_pending(*, limit: int | None = None) -> dict[str, int]:
        batch_size = min(
            max(int(limit or current_app.config.get("OUTBOX_BATCH_SIZE", 100)), 1),
            500,
        )
        ids = [
            row_id
            for row_id, in (
                db.session.query(TaskOutbox.id)
                .filter(
                    TaskOutbox.status == "PENDING",
                    TaskOutbox.available_at <= utcnow(),
                )
                .order_by(TaskOutbox.available_at, TaskOutbox.id)
                .limit(batch_size)
                .all()
            )
        ]
        db.session.rollback()
        dispatched = 0
        pending = 0
        for entry_id in ids:
            if OutboxDispatcher.dispatch_one(entry_id):
                dispatched += 1
            else:
                pending += 1
        return {"selected": len(ids), "dispatched": dispatched, "pending": pending}


# Backwards-compatible alias; use-case Services live in ``app.services.outbox``.
OutboxService = OutboxDispatcher
