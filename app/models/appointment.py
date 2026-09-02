"""Serviços, profissionais, horários e agendamentos."""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.base import CrudMixin, ReprMixin, TenantMixin, TimestampMixin


professional_services = db.Table(
    "professional_services",
    db.Column("company_id", db.Integer, primary_key=True),
    db.Column(
        "professional_id",
        db.Integer,
        primary_key=True,
    ),
    db.Column(
        "service_id",
        db.Integer,
        primary_key=True,
    ),
    db.ForeignKeyConstraint(
        ["professional_id", "company_id"],
        ["professionals.id", "professionals.company_id"],
        ondelete="CASCADE",
        name="fk_professional_services_professional_tenant",
    ),
    db.ForeignKeyConstraint(
        ["service_id", "company_id"],
        ["services.id", "services.company_id"],
        ondelete="CASCADE",
        name="fk_professional_services_service_tenant",
    ),
    db.Index("ix_professional_services_company", "company_id"),
)


class Service(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    duration_minutes = db.Column(db.Integer, nullable=False, default=30)
    buffer_minutes = db.Column(db.Integer, nullable=False, default=0)
    price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    professionals = db.relationship(
        "Professional",
        secondary=professional_services,
        back_populates="services",
        lazy="selectin",
        primaryjoin=lambda: db.and_(
            Service.id == professional_services.c.service_id,
            Service.company_id == professional_services.c.company_id,
        ),
        secondaryjoin=lambda: db.and_(
            Professional.id == professional_services.c.professional_id,
            Professional.company_id == professional_services.c.company_id,
        ),
        overlaps="services,professionals",
    )
    appointments = db.relationship("Appointment", back_populates="service", lazy="dynamic")

    __table_args__ = (
        db.UniqueConstraint("company_id", "name", name="uq_service_company_name"),
        db.UniqueConstraint("id", "company_id", name="uq_service_id_company"),
        db.CheckConstraint("duration_minutes > 0", name="ck_service_duration"),
        db.CheckConstraint("buffer_minutes >= 0", name="ck_service_buffer"),
        db.CheckConstraint("price >= 0", name="ck_service_price"),
    )


class Professional(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "professionals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(32))
    color = db.Column(db.String(16), nullable=False, default="#6D5DFB")
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    services = db.relationship(
        "Service",
        secondary=professional_services,
        back_populates="professionals",
        lazy="selectin",
        primaryjoin=lambda: db.and_(
            Professional.id == professional_services.c.professional_id,
            Professional.company_id == professional_services.c.company_id,
        ),
        secondaryjoin=lambda: db.and_(
            Service.id == professional_services.c.service_id,
            Service.company_id == professional_services.c.company_id,
        ),
        overlaps="services,professionals",
    )
    appointments = db.relationship(
        "Appointment", back_populates="professional", lazy="dynamic"
    )
    business_hours = db.relationship(
        "BusinessHour",
        back_populates="professional",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("company_id", "email", name="uq_professional_company_email"),
        db.UniqueConstraint("id", "company_id", name="uq_professional_id_company"),
    )


class BusinessHour(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "business_hours"

    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(
        db.Integer,
        db.ForeignKey("professionals.id", ondelete="CASCADE"),
        index=True,
    )
    weekday = db.Column(db.SmallInteger, nullable=False)
    opens_at = db.Column(db.Time)
    closes_at = db.Column(db.Time)
    is_closed = db.Column(db.Boolean, nullable=False, default=False)

    professional = db.relationship("Professional", back_populates="business_hours")

    __table_args__ = (
        db.UniqueConstraint(
            "company_id",
            "professional_id",
            "weekday",
            name="uq_business_hour_scope_weekday",
        ),
        db.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_business_hours_weekday"),
        db.CheckConstraint(
            "is_closed = 1 OR (opens_at IS NOT NULL AND closes_at IS NOT NULL AND opens_at < closes_at)",
            name="ck_business_hours_window",
        ),
        db.Index("ix_business_hours_company_weekday", "company_id", "weekday"),
    )


class ScheduleBlock(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "schedule_blocks"

    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(
        db.Integer,
        db.ForeignKey("professionals.id", ondelete="CASCADE"),
        index=True,
    )
    title = db.Column(db.String(160), nullable=False, default="Indisponível")
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    all_day = db.Column(db.Boolean, nullable=False, default=False)

    professional = db.relationship("Professional")

    __table_args__ = (
        db.CheckConstraint("ends_at > starts_at", name="ck_schedule_blocks_window"),
        db.Index(
            "ix_schedule_block_company_window", "company_id", "starts_at", "ends_at"
        ),
    )


class Appointment(db.Model, CrudMixin, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    service_id = db.Column(
        db.Integer,
        db.ForeignKey("services.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    professional_id = db.Column(
        db.Integer,
        db.ForeignKey("professionals.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(24), nullable=False, default="CONFIRMED", index=True)
    notes = db.Column(db.Text)
    external_reference = db.Column(db.String(190))
    idempotency_key = db.Column(db.String(190))
    cancelled_at = db.Column(db.DateTime)
    cancellation_reason = db.Column(db.String(255))

    customer = db.relationship("Customer", back_populates="appointments")
    service = db.relationship("Service", back_populates="appointments")
    professional = db.relationship("Professional", back_populates="appointments")
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])

    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "idempotency_key", name="uq_appointment_idempotency"
        ),
        db.CheckConstraint("ends_at > starts_at", name="ck_appointments_window"),
        db.CheckConstraint(
            "status IN ('PENDING','CONFIRMED','COMPLETED','CANCELLED','NO_SHOW')",
            name="ck_appointments_status",
        ),
        db.Index(
            "ix_appointment_professional_window",
            "company_id",
            "professional_id",
            "starts_at",
            "ends_at",
        ),
        db.Index("ix_appointment_company_status", "company_id", "status"),
    )
