"""Company and membership models."""

from __future__ import annotations

from app.extensions import db
from app.models.base import ReprMixin, TenantMixin, TimestampMixin


class Company(db.Model, TimestampMixin, ReprMixin):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(120), nullable=False, unique=True, index=True)
    legal_name = db.Column(db.String(200))
    tax_id = db.Column(db.String(32), unique=True)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(32))
    timezone = db.Column(db.String(64), nullable=False, default="America/Sao_Paulo")
    plan = db.Column(db.String(32), nullable=False, default="STARTER")
    status = db.Column(db.String(24), nullable=False, default="ACTIVE", index=True)
    settings_json = db.Column("settings", db.JSON, nullable=False, default=dict)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('ACTIVE', 'TRIAL', 'SUSPENDED', 'CANCELLED')",
            name="ck_companies_status",
        ),
    )

    memberships = db.relationship(
        "CompanyMember",
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    @property
    def is_active(self) -> bool:
        return self.status in {"ACTIVE", "TRIAL"}


class CompanyMember(db.Model, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "company_members"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(16), nullable=False, default="AGENT")
    status = db.Column(db.String(16), nullable=False, default="ACTIVE")
    invited_at = db.Column(db.DateTime)
    joined_at = db.Column(db.DateTime)

    company = db.relationship("Company", back_populates="memberships")
    user = db.relationship("User", back_populates="memberships")

    __table_args__ = (
        db.UniqueConstraint("company_id", "user_id", name="uq_member_company_user"),
        db.CheckConstraint(
            "role IN ('OWNER', 'ADMIN', 'AGENT')", name="ck_company_members_role"
        ),
        db.CheckConstraint(
            "status IN ('INVITED', 'ACTIVE', 'DISABLED')",
            name="ck_company_members_status",
        ),
        db.Index("ix_member_company_role", "company_id", "role"),
    )

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"
