"""Agenda transacional, servicos, profissionais e bloqueios."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db, limiter
from app.models import (
    Appointment,
    BusinessHour,
    Customer,
    Notification,
    Professional,
    ScheduleBlock,
    Service,
)
from app.models.base import utcnow
from app.routes.helpers import coerce_bool, failure, model_dict, payload, record_audit, success
from app.services.appointment_service import AppointmentService
from app.services.exceptions import DomainError
from app.tenant import current_company_id, roles_required, tenant_get_or_404


bp = Blueprint("appointments", __name__, url_prefix="/appointments")


def _money(value) -> Decimal:
    raw = str(value or "0").replace("R$", "").replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Preco invalido") from exc
    if amount < 0:
        raise ValueError("Preco invalido")
    return amount


def _appointment_data(item: Appointment) -> dict:
    return {
        **model_dict(
            item,
            "id",
            "customer_id",
            "service_id",
            "professional_id",
            "starts_at",
            "ends_at",
            "status",
            "notes",
            "cancellation_reason",
        ),
        "customer_name": item.customer.name,
        "service_name": item.service.name,
        "professional_name": item.professional.name,
    }


@bp.get("")
@login_required
def index():
    company_id = current_company_id()
    local_now = AppointmentService.to_local(company_id, utcnow())
    start_arg = request.args.get("start")
    week_offset = min(104, max(-52, request.args.get("week", 0, type=int)))
    try:
        local_start = (
            datetime.fromisoformat(start_arg)
            if start_arg
            else local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=7 * week_offset)
        )
    except (TypeError, ValueError):
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = AppointmentService.normalize_datetime(company_id, local_start)
    local_end = local_start + timedelta(days=7)
    end = AppointmentService.normalize_datetime(company_id, local_end)
    appointments = (
        Appointment.for_company(company_id)
        .filter(Appointment.starts_at >= start, Appointment.starts_at < end)
        .order_by(Appointment.starts_at)
        .all()
    )
    services = Service.for_company(company_id).filter(Service.is_active.is_(True)).order_by(Service.name).all()
    professionals = Professional.for_company(company_id).filter(Professional.is_active.is_(True)).order_by(Professional.name).all()
    customers = Customer.for_company(company_id).filter(Customer.status == "ACTIVE").order_by(Customer.name).limit(500).all()
    business_hours = BusinessHour.for_company(company_id).order_by(BusinessHour.weekday).all()
    blocks = (
        ScheduleBlock.for_company(company_id)
        .filter(ScheduleBlock.ends_at >= start, ScheduleBlock.starts_at < end)
        .order_by(ScheduleBlock.starts_at)
        .all()
    )
    appointment_groups: dict[str, list] = {}
    for item in appointments:
        local_item_start = AppointmentService.to_local(company_id, item.starts_at)
        local_item_end = AppointmentService.to_local(company_id, item.ends_at)
        view = SimpleNamespace(
            id=item.id,
            professional_id=item.professional_id,
            time_label=local_item_start.strftime("%H:%M"),
            end_time_label=local_item_end.strftime("%H:%M"),
            customer_name=item.customer.name,
            customer_phone=item.customer.phone,
            service_name=item.service.name,
            professional_name=item.professional.name,
            duration_label=f"{int((item.ends_at - item.starts_at).total_seconds() // 60)} min",
            service_color=item.professional.color,
            status=item.status,
            status_label={"CONFIRMED": "Confirmado", "PENDING": "Pendente", "CANCELLED": "Cancelado", "COMPLETED": "Concluido", "NO_SHOW": "Nao compareceu"}.get(item.status, item.status),
        )
        appointment_groups.setdefault(local_item_start.strftime("%d/%m/%Y"), []).append(view)
    local_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = AppointmentService.normalize_datetime(company_id, local_today)
    tomorrow = AppointmentService.normalize_datetime(
        company_id, local_today + timedelta(days=1)
    )
    appointment_stats = SimpleNamespace(
        today=Appointment.for_company(company_id).filter(Appointment.starts_at >= today, Appointment.starts_at < tomorrow).count(),
        confirmed=Appointment.for_company(company_id).filter(Appointment.status == "CONFIRMED", Appointment.starts_at >= today).count(),
        pending=Appointment.for_company(company_id).filter(Appointment.status == "PENDING", Appointment.starts_at >= today).count(),
        created_by_ai=Appointment.for_company(company_id).filter(Appointment.created_by_user_id.is_(None), Appointment.starts_at >= today).count(),
    )
    for service in services:
        service.active = service.is_active
        service.price_label = "R$ " + f"{service.price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        service.appointments_count = service.appointments.count()
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    business_hour_view = {}
    for row in business_hours:
        if row.professional_id is None:
            business_hour_view[day_names[row.weekday]] = {
                "enabled": not row.is_closed,
                "start": row.opens_at.strftime("%H:%M") if row.opens_at else "09:00",
                "end": row.closes_at.strftime("%H:%M") if row.closes_at else "18:00",
            }
    block_views = [
        SimpleNamespace(
            id=block.id,
            title=block.title,
            period_label=(
                f"{AppointmentService.to_local(company_id, block.starts_at).strftime('%d/%m/%Y %H:%M')} a "
                f"{AppointmentService.to_local(company_id, block.ends_at).strftime('%d/%m/%Y %H:%M')}"
            ),
        )
        for block in blocks
    ]
    company_settings = dict(current_user.active_company.settings_json or {})
    appointment_settings = SimpleNamespace(
        minimum_notice_hours=company_settings.get("minimum_notice_hours", 2),
        booking_window_days=company_settings.get("booking_window_days", 60),
        slot_interval=company_settings.get("slot_interval", 30),
    )
    return render_template(
        "appointments/index.html",
        appointments=appointments,
        services=services,
        professionals=professionals,
        customers=customers,
        business_hours=business_hour_view,
        blocks=blocks,
        blocked_periods=block_views,
        appointment_groups=appointment_groups,
        appointment_stats=appointment_stats,
        appointment_settings=appointment_settings,
        today_iso=local_now.date().isoformat(),
        agenda_period_label=f"{local_start.strftime('%d/%m')} a {(local_end - timedelta(days=1)).strftime('%d/%m/%Y')}",
        period={"start": start, "end": end},
    )


@bp.get("/availability")
@login_required
def availability():
    try:
        slots = AppointmentService.available_slots(
            current_company_id(),
            service_id=int(request.args.get("service_id", 0)),
            professional_id=request.args.get("professional_id", type=int),
            day=request.args.get("date", ""),
            limit=min(100, request.args.get("limit", 30, type=int)),
        )
    except (DomainError, ValueError) as exc:
        message = exc.message if isinstance(exc, DomainError) else "Parametros invalidos."
        status = exc.status_code if isinstance(exc, DomainError) else 422
        return jsonify(ok=False, message=message), status
    return jsonify(ok=True, slots=slots)


@bp.post("")
@bp.post("/create")
@login_required
@limiter.limit("30 per minute")
def create():
    data = payload()
    starts_at = data.get("starts_at", data.get("start"))
    if not starts_at and data.get("date") and data.get("time"):
        starts_at = f"{data['date']}T{data['time']}"
    try:
        appointment = AppointmentService.create(
            current_company_id(),
            customer_id=int(data.get("customer_id", 0)),
            service_id=int(data.get("service_id", 0)),
            professional_id=int(data.get("professional_id", 0)),
            starts_at=starts_at,
            notes=data.get("notes"),
            created_by_user_id=current_user.id,
            idempotency_key=request.headers.get("Idempotency-Key") or data.get("idempotency_key"),
        )
    except (DomainError, ValueError, TypeError) as exc:
        message = exc.message if isinstance(exc, DomainError) else "Revise os dados do agendamento."
        status = exc.status_code if isinstance(exc, DomainError) else 422
        return failure(message, status=status)
    notification = Notification(
        company_id=current_company_id(),
        notification_type="NEW_APPOINTMENT",
        title="Novo agendamento",
        body=f"{appointment.customer.name} agendou {appointment.service.name}.",
        link_url="/appointments",
        data_json={"appointment_id": appointment.id},
    )
    db.session.add(notification)
    record_audit("appointment.create", appointment)
    db.session.commit()
    return success("Agendamento confirmado.", data=_appointment_data(appointment), endpoint="appointments.index", status=201)


@bp.post("/<int:appointment_id>/cancel")
@login_required
def cancel(appointment_id: int):
    try:
        appointment = AppointmentService.cancel(
            current_company_id(), appointment_id, reason=payload().get("reason")
        )
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    db.session.add(
        Notification(
            company_id=current_company_id(),
            notification_type="APPOINTMENT_CANCELLED",
            title="Agendamento cancelado",
            body=f"{appointment.customer.name} - {appointment.service.name}",
            link_url="/appointments",
            data_json={"appointment_id": appointment.id},
        )
    )
    record_audit("appointment.cancel", appointment)
    db.session.commit()
    return success("Agendamento cancelado.", data=_appointment_data(appointment))


@bp.post("/services")
@login_required
@roles_required("ADMIN", "OWNER")
def create_service():
    data = payload()
    try:
        service = Service(
            company_id=current_company_id(),
            name=str(data.get("name", "")).strip()[:160],
            description=str(data.get("description", "")).strip() or None,
            duration_minutes=int(data.get("duration_minutes", 30)),
            buffer_minutes=int(data.get("buffer_minutes", 0)),
            price=_money(data.get("price")),
            is_active=coerce_bool(data.get("active", data.get("is_active")), True),
        )
        if not service.name or service.duration_minutes <= 0 or service.buffer_minutes < 0:
            raise ValueError
        db.session.add(service)
        db.session.flush()
        record_audit("service.create", service)
        db.session.commit()
    except (ValueError, IntegrityError):
        db.session.rollback()
        return failure("Revise nome, duracao, intervalo e preco.", status=422)
    return success("Servico criado.", data=model_dict(service, "id", "name", "duration_minutes", "buffer_minutes", "price"), status=201)


@bp.post("/professionals")
@login_required
@roles_required("ADMIN", "OWNER")
def create_professional():
    data = payload()
    professional = Professional(
        company_id=current_company_id(),
        name=str(data.get("name", "")).strip()[:160],
        email=str(data.get("email", "")).strip().lower()[:255] or None,
        phone=str(data.get("phone", "")).strip()[:32] or None,
        color=str(data.get("color", "#14b8a6"))[:16],
        is_active=True,
    )
    if not professional.name:
        return failure("Informe o nome do profissional.", status=422)
    service_ids = data.get("service_ids", [])
    if isinstance(service_ids, str):
        service_ids = [int(value) for value in service_ids.split(",") if value.strip().isdigit()]
    professional.services = Service.for_company(current_company_id()).filter(Service.id.in_(service_ids)).all() if service_ids else []
    try:
        db.session.add(professional)
        db.session.flush()
        record_audit("professional.create", professional)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return failure("Ja existe um profissional com este e-mail.", status=409)
    return success("Profissional criado.", data=model_dict(professional, "id", "name", "email", "color"), status=201)


@bp.post("/business-hours")
@login_required
@roles_required("ADMIN", "OWNER")
def save_business_hour():
    data = payload()
    company_id = current_company_id()
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if any(f"{name}_start" in data for name in day_names):
        try:
            for weekday, name in enumerate(day_names):
                row = BusinessHour.for_company(company_id).filter_by(
                    professional_id=None, weekday=weekday
                ).first()
                if row is None:
                    row = BusinessHour(company_id=company_id, professional_id=None, weekday=weekday)
                    db.session.add(row)
                enabled = coerce_bool(data.get(f"{name}_enabled"), False)
                row.is_closed = not enabled
                row.opens_at = time.fromisoformat(str(data.get(f"{name}_start", "09:00"))) if enabled else None
                row.closes_at = time.fromisoformat(str(data.get(f"{name}_end", "18:00"))) if enabled else None
                if enabled and row.opens_at >= row.closes_at:
                    raise ValueError
            db.session.commit()
            return success("Horarios da semana salvos.")
        except (ValueError, IntegrityError):
            db.session.rollback()
            return failure("Revise os horarios informados.", status=422)
    try:
        weekday = int(data.get("weekday"))
        professional_id = int(data["professional_id"]) if data.get("professional_id") else None
        if professional_id:
            tenant_get_or_404(Professional, professional_id)
        row = BusinessHour.for_company(company_id).filter_by(
            professional_id=professional_id, weekday=weekday
        ).one_or_none()
        if row is None:
            row = BusinessHour(company_id=company_id, professional_id=professional_id, weekday=weekday)
            db.session.add(row)
        row.is_closed = coerce_bool(data.get("is_closed"), False)
        row.opens_at = None if row.is_closed else time.fromisoformat(str(data.get("opens_at", "09:00")))
        row.closes_at = None if row.is_closed else time.fromisoformat(str(data.get("closes_at", "18:00")))
        if not row.is_closed and row.opens_at >= row.closes_at:
            raise ValueError
        db.session.flush()
        record_audit("business_hour.save", row)
        db.session.commit()
    except (ValueError, TypeError, IntegrityError):
        db.session.rollback()
        return failure("Horario comercial invalido.", status=422)
    return success("Horario salvo.")


@bp.post("/blocks")
@login_required
@roles_required("ADMIN", "OWNER")
def create_block():
    data = payload()
    try:
        company_id = current_company_id()
        start = AppointmentService.normalize_datetime(company_id, data.get("starts_at", ""))
        end = AppointmentService.normalize_datetime(company_id, data.get("ends_at", ""))
        if end <= start:
            raise ValueError
        professional_id = int(data["professional_id"]) if data.get("professional_id") else None
        if professional_id:
            tenant_get_or_404(Professional, professional_id)
        block = ScheduleBlock(
            company_id=company_id,
            professional_id=professional_id,
            title=str(data.get("title", "Indisponivel"))[:160],
            starts_at=start,
            ends_at=end,
            all_day=coerce_bool(data.get("all_day")),
        )
        db.session.add(block)
        db.session.flush()
        record_audit("schedule_block.create", block)
        db.session.commit()
    except (ValueError, TypeError, IntegrityError):
        db.session.rollback()
        return failure("Periodo de bloqueio invalido.", status=422)
    return success("Bloqueio adicionado.", data=model_dict(block, "id", "title", "starts_at", "ends_at"), status=201)


@bp.delete("/blocks/<int:block_id>")
@bp.post("/blocks/<int:block_id>/delete")
@login_required
@roles_required("ADMIN", "OWNER")
def delete_block(block_id: int):
    block = tenant_get_or_404(ScheduleBlock, block_id)
    record_audit("schedule_block.delete", block)
    db.session.delete(block)
    db.session.commit()
    return success("Bloqueio removido.")


@bp.post("/<int:appointment_id>/confirm")
@login_required
def confirm(appointment_id: int):
    appointment = tenant_get_or_404(Appointment, appointment_id)
    if appointment.status == "CANCELLED":
        return failure("Agendamento cancelado nao pode ser confirmado.", status=409)
    appointment.status = "CONFIRMED"
    record_audit("appointment.confirm", appointment)
    db.session.commit()
    return success("Agendamento confirmado.")


@bp.post("/services/<int:service_id>/delete")
@login_required
@roles_required("ADMIN", "OWNER")
def delete_service(service_id: int):
    service = tenant_get_or_404(Service, service_id)
    service.is_active = False
    record_audit("service.archive", service)
    db.session.commit()
    return success("Servico arquivado.")


@bp.post("/settings")
@login_required
@roles_required("ADMIN", "OWNER")
def save_settings():
    data = payload()
    try:
        slot_interval = min(120, max(5, int(data.get("slot_interval", 30))))
        minimum_notice = min(720, max(0, int(data.get("minimum_notice_hours", 2))))
        booking_window = min(730, max(1, int(data.get("booking_window_days", 60))))
    except (TypeError, ValueError):
        return failure("Regras de agenda invalidas.", status=422)
    company = current_user.active_company
    settings = dict(company.settings_json or {})
    settings.update(
        slot_interval=slot_interval,
        minimum_notice_hours=minimum_notice,
        booking_window_days=booking_window,
    )
    company.settings_json = settings
    db.session.commit()
    return success("Regras da agenda salvas.")
