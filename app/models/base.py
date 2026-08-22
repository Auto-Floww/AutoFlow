"""Shared model helpers for tenant isolation and consistent timestamps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import declared_attr

from app.extensions import db


def utcnow() -> datetime:
    """Return a naive UTC timestamp, which is portable across MySQL and SQLite."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class TenantMixin:
    """Adds mandatory company ownership and safe query helpers."""

    @declared_attr
    def company_id(cls):  # noqa: N805 - SQLAlchemy declared attribute
        return db.Column(
            db.Integer,
            db.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )

    @declared_attr
    def company(cls):  # noqa: N805 - SQLAlchemy declared attribute
        return db.relationship("Company")

    @classmethod
    def for_company(cls, company_id: int):
        if company_id is None:
            raise ValueError("company_id is required")
        return cls.query.filter(cls.company_id == int(company_id))

    @classmethod
    def get_for_company(cls, company_id: int, object_id: int):
        return cls.for_company(company_id).filter(cls.id == object_id).one_or_none()

    def belongs_to(self, company_id: int) -> bool:
        return bool(company_id is not None and self.company_id == int(company_id))


class ReprMixin:
    def __repr__(self) -> str:
        label = getattr(self, "name", None) or getattr(self, "title", None)
        suffix = f" {label!r}" if label else ""
        return f"<{self.__class__.__name__} {getattr(self, 'id', None)}{suffix}>"


class CrudMixin:
    """Basic persistence kept on the model, without a redundant repository."""

    def salvar(self, *, commit: bool = True):
        db.session.add(self)
        db.session.commit() if commit else db.session.flush()
        return self

    def atualizar(self, *, commit: bool = True, **dados):
        for campo, valor in dados.items():
            if not hasattr(self, campo):
                raise AttributeError(f"Campo desconhecido: {campo}")
            setattr(self, campo, valor)
        db.session.commit() if commit else db.session.flush()
        return self

    def deletar(self, *, commit: bool = True) -> None:
        db.session.delete(self)
        db.session.commit() if commit else db.session.flush()

    @classmethod
    def listar_todos(cls):
        return cls.query.all()

    @classmethod
    def buscar_por_id(cls, object_id: int):
        return db.session.get(cls, int(object_id))


def as_dict(instance: Any, *fields: str) -> dict[str, Any]:
    return {field: getattr(instance, field) for field in fields}
