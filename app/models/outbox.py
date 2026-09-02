"""Outbox transacional para envio confiável de tarefas ao Celery."""

from __future__ import annotations

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TimestampMixin, utcnow


OUTBOX_TASK_NAMES = (
    "process_message",
    "send_whatsapp_message",
    "generate_summary",
    "password_reset_email",
    "process_appointment",
    "send_notification",
)


class TaskOutbox(db.Model, CrudMixin, TimestampMixin, ReprMixin):
    """Garante que a tarefa seja salva junto com a alteração que a criou."""

    __tablename__ = "task_outbox"

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    task_name = db.Column(db.String(64), nullable=False, index=True)
    idempotency_key = db.Column(db.String(190), nullable=False, unique=True)
    payload_json = db.Column("payload", db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(16), nullable=False, default="PENDING", index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    last_attempt_at = db.Column(db.DateTime)
    dispatched_at = db.Column(db.DateTime)
    error = db.Column(db.Text)

    company = db.relationship("Company")

    __table_args__ = (
        db.CheckConstraint(
            "task_name IN ("
            "'process_message','send_whatsapp_message','generate_summary',"
            "'password_reset_email','process_appointment','send_notification'"
            ")",
            name="ck_task_outbox_task_name",
        ),
        db.CheckConstraint(
            "status IN ('PENDING','DISPATCHED')",
            name="ck_task_outbox_status",
        ),
        db.CheckConstraint("attempts >= 0", name="ck_task_outbox_attempts"),
        db.Index("ix_task_outbox_pending", "status", "available_at", "id"),
    )
