"""Tenant tags and explicit association models."""

from __future__ import annotations

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, TimestampMixin


class Tag(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    color = db.Column(db.String(16), nullable=False, default="#6D5DFB")
    tag_type = db.Column(db.String(24), nullable=False, default="GENERAL")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    customer_links = db.relationship(
        "CustomerTag",
        back_populates="tag",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    conversation_links = db.relationship(
        "ConversationTag",
        back_populates="tag",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "name", "tag_type", name="uq_tag_company_name_type"
        ),
        db.CheckConstraint(
            "tag_type IN ('GENERAL','CUSTOMER','CONVERSATION')", name="ck_tags_type"
        ),
    )


class CustomerTag(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "customer_tags"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id = db.Column(
        db.Integer,
        db.ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    customer = db.relationship("Customer", back_populates="tag_links")
    tag = db.relationship("Tag", back_populates="customer_links")

    __table_args__ = (
        db.UniqueConstraint("company_id", "customer_id", "tag_id", name="uq_customer_tag"),
    )


class ConversationTag(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "conversation_tags"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id = db.Column(
        db.Integer,
        db.ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    conversation = db.relationship("Conversation", back_populates="tag_links")
    tag = db.relationship("Tag", back_populates="conversation_links")

    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "conversation_id", "tag_id", name="uq_conversation_tag"
        ),
    )
