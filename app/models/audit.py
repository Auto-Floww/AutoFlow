"""Modelo de histórico de auditoria imutável."""

"""Novos registros podem ser adicionados, mas o historico nao deve ser alterado ou removido"""

from __future__ import annotations

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, utcnow


class AuditLog(db.Model, CrudMixin, TenantMixin, ReprMixin):
    __tablename__ = "audit_logs"

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    actor_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=False, index=True)
    entity_id = db.Column(db.String(100), index=True)
    changes_json = db.Column("changes", db.JSON, nullable=False, default=dict)
    context_json = db.Column("context", db.JSON, nullable=False, default=dict)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    actor_user = db.relationship("User", foreign_keys=[actor_user_id])

    __table_args__ = (
        db.Index(
            "ix_audit_company_entity",
            "company_id",
            "entity_type",
            "entity_id",
            "created_at",
        ),
    )
