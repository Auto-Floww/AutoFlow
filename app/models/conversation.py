"""Conversation state and memory."""

from __future__ import annotations

from app.extensions import db
from app.models.base import ReprMixin, TenantMixin, TimestampMixin


class Conversation(db.Model, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    whatsapp_integration_id = db.Column(
        db.Integer,
        db.ForeignKey("whatsapp_integrations.id", ondelete="SET NULL"),
        index=True,
    )
    channel = db.Column(db.String(24), nullable=False, default="WHATSAPP")
    external_id = db.Column(db.String(190))
    status = db.Column(db.String(24), nullable=False, default="OPEN", index=True)
    ai_status = db.Column(db.String(24), nullable=False, default="ACTIVE", index=True)
    human_requested = db.Column(db.Boolean, nullable=False, default=False)
    unread_count = db.Column(db.Integer, nullable=False, default=0)
    last_message_at = db.Column(db.DateTime, index=True)
    closed_at = db.Column(db.DateTime)
    summary = db.Column(db.Text)
    memory_json = db.Column("memory", db.JSON, nullable=False, default=dict)

    customer = db.relationship("Customer", back_populates="conversations")
    assigned_user = db.relationship("User", foreign_keys=[assigned_user_id])
    whatsapp_integration = db.relationship("WhatsAppIntegration")
    messages = db.relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="dynamic",
        order_by="Message.created_at",
    )
    tag_links = db.relationship(
        "ConversationTag",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "channel", "external_id", name="uq_conversation_external"
        ),
        db.CheckConstraint(
            "status IN ('OPEN','PENDING','RESOLVED','CLOSED')",
            name="ck_conversations_status",
        ),
        db.CheckConstraint(
            "ai_status IN ('ACTIVE','PAUSED','DISABLED')",
            name="ck_conversations_ai_status",
        ),
        db.CheckConstraint("unread_count >= 0", name="ck_conversations_unread"),
        db.Index("ix_conversation_company_last", "company_id", "last_message_at"),
        db.Index("ix_conversation_company_status", "company_id", "status"),
    )

    @property
    def ai_active(self) -> bool:
        return self.ai_status == "ACTIVE"

    @ai_active.setter
    def ai_active(self, value: bool) -> None:
        self.ai_status = "ACTIVE" if value else "PAUSED"
