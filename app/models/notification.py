"""In-app notifications."""

from __future__ import annotations

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, TimestampMixin


class Notification(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    notification_type = db.Column(db.String(48), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text)
    link_url = db.Column(db.String(500))
    data_json = db.Column("data", db.JSON, nullable=False, default=dict)
    idempotency_key = db.Column(db.String(190))
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    read_at = db.Column(db.DateTime)

    user = db.relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "idempotency_key", name="uq_notification_idempotency"
        ),
        db.Index("ix_notification_user_unread", "company_id", "user_id", "is_read"),
        db.Index("ix_notification_company_created", "company_id", "created_at"),
    )
