"""models de mensagem da conversa com campos para evitar duplicidade no webhook"""

from __future__ import annotations

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, TimestampMixin


class Message(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id = db.Column(
        db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    sender_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reply_to_id = db.Column(
        db.Integer, db.ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    external_message_id = db.Column(db.String(190))
    idempotency_key = db.Column(db.String(190))
    direction = db.Column(db.String(16), nullable=False)
    sender_type = db.Column(db.String(16), nullable=False)
    message_type = db.Column(db.String(24), nullable=False, default="TEXT")
    content = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(24), nullable=False, default="RECEIVED", index=True)
    processing_status = db.Column(db.String(24), nullable=False, default="PENDING")
    payload_json = db.Column("payload", db.JSON, nullable=False, default=dict)
    ai_metadata_json = db.Column("ai_metadata", db.JSON, nullable=False, default=dict)
    error_message = db.Column(db.Text)
    sent_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    read_at = db.Column(db.DateTime)
    processed_at = db.Column(db.DateTime)

    conversation = db.relationship("Conversation", back_populates="messages")
    customer = db.relationship("Customer", foreign_keys=[customer_id])
    sender_user = db.relationship("User", foreign_keys=[sender_user_id])
    reply_to = db.relationship("Message", remote_side=[id], foreign_keys=[reply_to_id])

    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "external_message_id", name="uq_message_external"
        ),
        db.UniqueConstraint(
            "company_id", "idempotency_key", name="uq_message_idempotency"
        ),
        db.CheckConstraint(
            "direction IN ('INBOUND','OUTBOUND','SYSTEM')",
            name="ck_messages_direction",
        ),
        db.CheckConstraint(
            "sender_type IN ('CUSTOMER','AI','AGENT','SYSTEM')",
            name="ck_messages_sender_type",
        ),
        db.CheckConstraint(
            "status IN ('RECEIVED','QUEUED','SENDING','SENT','DELIVERED','READ','FAILED')",
            name="ck_messages_status",
        ),
        db.CheckConstraint(
            "processing_status IN ('PENDING','PROCESSING','PROCESSED','SKIPPED','FAILED')",
            name="ck_messages_processing",
        ),
        db.Index("ix_message_conversation_created", "conversation_id", "created_at"),
        db.Index("ix_message_company_status", "company_id", "status"),
    )

    @property
    def text(self) -> str:
        return self.content

    @text.setter
    def text(self, value: str) -> None:
        self.content = value
