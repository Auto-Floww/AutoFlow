"""Model de aplicacao do usuario."""

from __future__ import annotations

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TimestampMixin, utcnow


class User(db.Model, CrudMixin, UserMixin, TimestampMixin, ReprMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(32))
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    email_verified_at = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    password_reset_at = db.Column(db.DateTime)
    reset_token_hash = db.Column(db.String(128), index=True)
    reset_token_expires_at = db.Column(db.DateTime)
    active_company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    active_company = db.relationship("Company", foreign_keys=[active_company_id])
    memberships = db.relationship(
        "CompanyMember",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    @property
    def is_active(self) -> bool:
        return bool(self.active)

    def get_id(self) -> str:
        """Versiona sessões e remember cookies pela última troca de senha."""

        version = (
            self.password_reset_at.strftime("%Y%m%d%H%M%S%f")
            if self.password_reset_at
            else "0"
        )
        return f"{self.id}.{version}"

    @property
    def full_name(self) -> str:
        return self.name

    @full_name.setter
    def full_name(self, value: str) -> None:
        self.name = value

    @property
    def company_id(self) -> int | None:
        if self.active_company_id:
            membership = self.membership_for(self.active_company_id)
            return membership.company_id if membership else None
        active_memberships = [
            membership
            for membership in self.memberships
            if membership.is_active
            and membership.company is not None
            and membership.company.is_active
        ]
        return active_memberships[0].company_id if active_memberships else None

    @property
    def company(self):
        """Compatibility alias for the currently selected workspace."""

        membership = self.membership_for(self.company_id) if self.company_id else None
        return membership.company if membership else None

    @property
    def role(self) -> str | None:
        company_id = self.company_id
        membership = next(
            (m for m in self.memberships if m.company_id == company_id and m.is_active),
            None,
        )
        return membership.role if membership else None

    def set_password(self, password: str) -> None:
        if not password or len(password) < 8:
            raise ValueError("Password must contain at least 8 characters")
        self.password_hash = generate_password_hash(password)
        self.password_reset_at = utcnow()

    def check_password(self, password: str) -> bool:
        return bool(password and check_password_hash(self.password_hash, password))

    def membership_for(self, company_id: int | None):
        if company_id is None:
            return None
        return next(
            (
                membership
                for membership in self.memberships
                if membership.company_id == int(company_id)
                and membership.is_active
                and membership.company is not None
                and membership.company.is_active
            ),
            None,
        )

    def can(self, *roles: str, company_id: int | None = None) -> bool:
        membership = self.membership_for(company_id or self.company_id)
        return bool(membership and membership.role in set(roles))
