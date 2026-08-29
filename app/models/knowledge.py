"""FAQ and knowledge-base content used by the assistant."""

from __future__ import annotations

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, TimestampMixin


class FAQ(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "faqs"

    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    priority = db.Column(db.Integer, nullable=False, default=100)

    __table_args__ = (
        db.Index("ix_faq_company_active", "company_id", "is_active", "category"),
    )


class KnowledgeDocument(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "knowledge_documents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    source_type = db.Column(db.String(32), nullable=False, default="TEXT")
    source_url = db.Column(db.String(500))
    mime_type = db.Column(db.String(100))
    checksum = db.Column(db.String(64), index=True)
    status = db.Column(db.String(24), nullable=False, default="READY", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    metadata_json = db.Column("metadata", db.JSON, nullable=False, default=dict)

    __table_args__ = (
        db.UniqueConstraint("company_id", "checksum", name="uq_knowledge_checksum"),
        db.CheckConstraint(
            "status IN ('PROCESSING','READY','FAILED')", name="ck_knowledge_status"
        ),
        db.Index("ix_knowledge_company_active", "company_id", "is_active", "status"),
    )
