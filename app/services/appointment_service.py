"""Availability and booking operations with per-professional locking."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    Appointment,
    BusinessHour,
    Company,
    Customer,
    Professional,
    ScheduleBlock,
    Service,
)
from app.models.base import utcnow
from app.services.exceptions import ConflictError, ValidationError
from app.services.tenancy import ensure_same_company, tenant_get


ACTIVE_APPOINTMENT_STATUSES = ("PENDING", "CONFIRMED")
DEFAULT_BOOKING_RULES = {
    "slot_interval": 30,
    "minimum_notice_hours": 2,
    "booking_window_days": 60,
}


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError("Invalid company timezone") from exc


def _parse_datetime(value: datetime | str, timezone_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError("Date/time must use ISO 8601 format") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValidationError("A date/time value is required")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_timezone(timezone_name))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _to_local(value: datetime, timezone_name: str) -> datetime:
    return value.replace(tzinfo=timezone.utc).astimezone(_timezone(timezone_name))


class AppointmentOperations:
    @staticmethod
    def _company(company_id: int) -> Company:
        company = Company.query.filter_by(id=int(company_id)).one_or_none()
        if company is None:
            raise ValidationError("Company not found")
        return company

    @staticmethod
    def get(company_id: int, appointment_id: int) -> Appointment:
        return tenant_get(Appointment, company_id, appointment_id)

    @staticmethod
    def booking_rules(company: Company) -> dict[str, int]:
        settings = dict(company.settings_json or {})
        try:
            slot_interval = min(
                120,
                max(5, int(settings.get("slot_interval", DEFAULT_BOOKING_RULES["slot_interval"]))),
            )
            minimum_notice_hours = min(
                720,
                max(
                    0,
                    int(
                        settings.get(
                            "minimum_notice_hours",
                            DEFAULT_BOOKING_RULES["minimum_notice_hours"],
                        )
                    ),
                ),
            )
            booking_window_days = min(
                730,
                max(
                    1,
                    int(
                        settings.get(
                            "booking_window_days",
                            DEFAULT_BOOKING_RULES["booking_window_days"],
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            return dict(DEFAULT_BOOKING_RULES)
        return {
            "slot_interval": slot_interval,
            "minimum_notice_hours": minimum_notice_hours,
            "booking_window_days": booking_window_days,
        }

    @staticmethod
    def normalize_datetime(company_id: int, value: datetime | str) -> datetime:
        company = AppointmentOperations._company(company_id)
        return _parse_datetime(value, company.timezone)

    @staticmethod
    def to_local(company_id: int, value: datetime) -> datetime:
        company = AppointmentOperations._company(company_id)
        return _to_local(value, company.timezone)

    @staticmethod
    def _within_booking_window(company: Company, start_utc: datetime) -> bool:
        rules = AppointmentOperations.booking_rules(company)
        now_utc = utcnow()
        earliest = now_utc + timedelta(hours=rules["minimum_notice_hours"])
        latest = now_utc + timedelta(days=rules["booking_window_days"])
        return earliest <= start_utc <= latest

    @staticmethod
    def _business_window(
        company_id: int, professional_id: int, local_day: date
    ) -> tuple[time, time] | None:
        rows = (
            BusinessHour.for_company(company_id)
            .filter(
                BusinessHour.weekday == local_day.weekday(),
                db.or_(
                    BusinessHour.professional_id == professional_id,
                    BusinessHour.professional_id.is_(None),
                ),
            )
            .order_by(BusinessHour.professional_id.desc())
            .all()
        )
        if not rows:
            return None
        selected = next((row for row in rows if row.professional_id == professional_id), rows[0])
        if selected.is_closed or not selected.opens_at or not selected.closes_at:
            return None
        return selected.opens_at, selected.closes_at

    @staticmethod
    def _overlap_exists(
        company_id: int,
        professional_id: int,
        starts_at: datetime,
        ends_at: datetime,
        *,
        exclude_appointment_id: int | None = None,
        lock: bool = False,
    ) -> bool:
        appointment_query = Appointment.for_company(company_id).filter(
            Appointment.professional_id == professional_id,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            Appointment.starts_at < ends_at,
            Appointment.ends_at > starts_at,
        )
        if exclude_appointment_id:
            appointment_query = appointment_query.filter(
                Appointment.id != exclude_appointment_id
            )
        if lock:
            appointment_query = appointment_query.with_for_update()
        if appointment_query.first() is not None:
            return True
        block_query = ScheduleBlock.for_company(company_id).filter(
            db.or_(
                ScheduleBlock.professional_id == professional_id,
                ScheduleBlock.professional_id.is_(None),
            ),
            ScheduleBlock.starts_at < ends_at,
            ScheduleBlock.ends_at > starts_at,
        )
        if lock:
            block_query = block_query.with_for_update()
        block = block_query.first()
        return block is not None

    @staticmethod
    def is_available(
        company_id: int,
        *,
        professional_id: int,
        service_id: int,
        starts_at: datetime | str,
        lock_professional: bool = False,
        lock_conflicts: bool | None = None,
    ) -> tuple[bool, datetime, datetime]:
        company = AppointmentOperations._company(company_id)
        professional_query = Professional.for_company(company_id).filter(
            Professional.id == professional_id, Professional.is_active.is_(True)
        )
        if lock_professional:
            professional_query = professional_query.with_for_update()
        professional = professional_query.one_or_none()
        service = Service.for_company(company_id).filter(
            Service.id == service_id, Service.is_active.is_(True)
        ).one_or_none()
        if professional is None or service is None:
            raise ValidationError("Professional or service is not available")
        ensure_same_company(company_id, professional, service)
        if professional.services and service not in professional.services:
            raise ValidationError("Professional does not provide this service")
        start_utc = _parse_datetime(starts_at, company.timezone)
        end_utc = start_utc + timedelta(
            minutes=service.duration_minutes + service.buffer_minutes
        )
        local_start = _to_local(start_utc, company.timezone)
        local_end = _to_local(end_utc, company.timezone)
        window = AppointmentOperations._business_window(
            company_id, professional.id, local_start.date()
        )
        if window is None or local_start.date() != local_end.date():
            return False, start_utc, end_utc
        opens_at, closes_at = window
        rules = AppointmentOperations.booking_rules(company)
        opening_minutes = opens_at.hour * 60 + opens_at.minute
        start_minutes = local_start.hour * 60 + local_start.minute
        aligned_to_slot = (
            start_minutes - opening_minutes
        ) % rules["slot_interval"] == 0
        within_hours = local_start.time().replace(tzinfo=None) >= opens_at and local_end.time().replace(
            tzinfo=None
        ) <= closes_at
        available = (
            AppointmentOperations._within_booking_window(company, start_utc)
            and aligned_to_slot
            and within_hours
            and not AppointmentOperations._overlap_exists(
            company_id,
            professional.id,
            start_utc,
            end_utc,
            lock=lock_professional if lock_conflicts is None else lock_conflicts,
            )
        )
        return available, start_utc, end_utc

    @staticmethod
    def available_slots(
        company_id: int,
        *,
        service_id: int,
        day: date | str,
        professional_id: int | None = None,
        step_minutes: int | None = None,
        limit: int = 30,
    ) -> list[dict]:
        company = AppointmentOperations._company(company_id)
        if isinstance(day, str):
            try:
                local_day = date.fromisoformat(day)
            except ValueError as exc:
                raise ValidationError("Date must use YYYY-MM-DD format") from exc
        else:
            local_day = day
        service = tenant_get(Service, company_id, service_id)
        query = Professional.for_company(company_id).filter(Professional.is_active.is_(True))
        if professional_id:
            query = query.filter(Professional.id == professional_id)
        professionals = query.all()
        results: list[dict] = []
        tenant_tz = _timezone(company.timezone)
        rules = AppointmentOperations.booking_rules(company)
        earliest_utc = utcnow() + timedelta(hours=rules["minimum_notice_hours"])
        latest_utc = utcnow() + timedelta(days=rules["booking_window_days"])
        # A granularidade é política da empresa e não pode ser substituída pelo cliente.
        step = timedelta(minutes=rules["slot_interval"])
        duration = timedelta(minutes=service.duration_minutes + service.buffer_minutes)
        for professional in professionals:
            if professional.services and service not in professional.services:
                continue
            window = AppointmentOperations._business_window(
                company_id, professional.id, local_day
            )
            if window is None:
                continue
            local_cursor = datetime.combine(local_day, window[0], tenant_tz)
            local_close = datetime.combine(local_day, window[1], tenant_tz)
            while local_cursor + duration <= local_close and len(results) < min(limit, 100):
                start_utc = local_cursor.astimezone(timezone.utc).replace(tzinfo=None)
                end_utc = start_utc + duration
                if earliest_utc <= start_utc <= latest_utc and not AppointmentOperations._overlap_exists(
                    company_id, professional.id, start_utc, end_utc
                ):
                    results.append(
                        {
                            "professional_id": professional.id,
                            "professional_name": professional.name,
                            "time": local_cursor.strftime("%H:%M"),
                            "value": local_cursor.strftime("%H:%M"),
                            "label": local_cursor.strftime("%H:%M"),
                            "starts_at": local_cursor.isoformat(),
                            "ends_at": (local_cursor + duration).isoformat(),
                            "timezone": company.timezone,
                        }
                    )
                local_cursor += step
            if len(results) >= min(limit, 100):
                break
        return sorted(results, key=lambda item: item["starts_at"])[:limit]

    @staticmethod
    def create(
        company_id: int,
        *,
        customer_id: int,
        service_id: int,
        professional_id: int,
        starts_at: datetime | str,
        notes: str | None = None,
        created_by_user_id: int | None = None,
        idempotency_key: str | None = None,
        external_reference: str | None = None,
        commit: bool = True,
    ) -> Appointment:
        if idempotency_key:
            existing = Appointment.query.filter_by(
                company_id=int(company_id), idempotency_key=idempotency_key
            ).one_or_none()
            if existing:
                return existing
        customer = tenant_get(Customer, company_id, customer_id)
        # Serialize all booking decisions for one professional on a stable row.
        locked_professional = (
            Professional.for_company(company_id)
            .filter(Professional.id == professional_id, Professional.is_active.is_(True))
            .with_for_update()
            .one_or_none()
        )
        if locked_professional is None:
            raise ValidationError("Professional is not available")
        # Recheck after the lock. Locking reads observe concurrent commits even under
        # MySQL's default REPEATABLE READ isolation.
        if idempotency_key:
            existing = Appointment.query.filter_by(
                company_id=int(company_id), idempotency_key=idempotency_key
            ).with_for_update().one_or_none()
            if existing:
                return existing
        available, start_utc, end_utc = AppointmentOperations.is_available(
            company_id,
            professional_id=professional_id,
            service_id=service_id,
            starts_at=starts_at,
            lock_professional=False,
            lock_conflicts=True,
        )
        if not available:
            raise ConflictError("The selected appointment time is no longer available")
        appointment = Appointment(
            company_id=int(company_id),
            customer_id=customer.id,
            service_id=service_id,
            professional_id=professional_id,
            starts_at=start_utc,
            ends_at=end_utc,
            notes=notes,
            created_by_user_id=created_by_user_id,
            idempotency_key=idempotency_key,
            external_reference=external_reference,
            status="CONFIRMED",
        )
        db.session.add(appointment)
        try:
            db.session.flush()
            if commit:
                db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            if idempotency_key:
                existing = Appointment.query.filter_by(
                    company_id=int(company_id), idempotency_key=idempotency_key
                ).one_or_none()
                if existing:
                    return existing
            raise ConflictError("Appointment could not be created") from exc
        return appointment

    @staticmethod
    def cancel(
        company_id: int,
        appointment_id: int,
        *,
        reason: str | None = None,
        commit: bool = True,
    ) -> Appointment:
        appointment = tenant_get(Appointment, company_id, appointment_id, lock=True)
        if appointment.status == "CANCELLED":
            return appointment
        if appointment.status in {"COMPLETED", "NO_SHOW"}:
            raise ConflictError("A completed appointment cannot be cancelled")
        appointment.status = "CANCELLED"
        appointment.cancelled_at = utcnow()
        appointment.cancellation_reason = (reason or "")[:255] or None
        if commit:
            db.session.commit()
        return appointment


# Backwards-compatible import for integrations that still use the former facade.
AppointmentService = AppointmentOperations
get_available_appointments = AppointmentOperations.available_slots
create_appointment = AppointmentOperations.create
cancel_appointment = AppointmentOperations.cancel
