"""Disponibilidade, criação transacional e prevenção de conflito."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models import (
    Appointment,
    BusinessHour,
    Customer,
    Professional,
    ScheduleBlock,
    Service,
)


def _schedule(company_id: int):
    customer = Customer(
        company_id=company_id,
        name="Cliente Agenda",
        phone="+5511999112233",
        phone_normalized="5511999112233",
    )
    service = Service(
        company_id=company_id,
        name="Consultoria",
        duration_minutes=60,
        buffer_minutes=0,
        price="100.00",
    )
    professional = Professional(company_id=company_id, name="Dra. Ana")
    professional.services.append(service)
    db.session.add_all([customer, service, professional])
    db.session.flush()
    db.session.add(
        BusinessHour(
            company_id=company_id,
            professional_id=professional.id,
            weekday=0,
            opens_at=time(9, 0),
            closes_at=time(18, 0),
        )
    )
    db.session.commit()
    return customer, service, professional


def _future_monday(hour: int, minute: int = 0) -> datetime:
    local_now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    target_day = (local_now + timedelta(days=14)).date()
    target_day += timedelta(days=(7 - target_day.weekday()) % 7)
    return datetime.combine(
        target_day, time(hour, minute), tzinfo=ZoneInfo("America/Sao_Paulo")
    )


def test_availability_and_booking_use_company_timezone(
    client, login_as, tenant_user
):
    customer, service, professional = _schedule(tenant_user.company_id)
    login_as(tenant_user)
    local_start = _future_monday(10)

    availability = client.get(
        "/appointments/availability",
        query_string={
            "service_id": service.id,
            "professional_id": professional.id,
            "date": local_start.date().isoformat(),
        },
    )
    assert availability.status_code == 200
    assert availability.get_json()["slots"]

    created = client.post(
        "/appointments",
        json={
            "customer_id": customer.id,
            "service_id": service.id,
            "professional_id": professional.id,
            "starts_at": local_start.isoformat(),
        },
        headers={"Idempotency-Key": "agenda-001"},
    )

    assert created.status_code == 201
    appointment = db.session.get(Appointment, created.get_json()["data"]["id"])
    assert appointment.status == "CONFIRMED"
    expected_utc = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    assert appointment.starts_at == expected_utc
    assert appointment.ends_at == expected_utc + timedelta(hours=1)


def test_double_booking_is_rejected(client, login_as, tenant_user):
    customer, service, professional = _schedule(tenant_user.company_id)
    login_as(tenant_user)
    local_start = _future_monday(10)
    first_data = {
        "customer_id": customer.id,
        "service_id": service.id,
        "professional_id": professional.id,
        "starts_at": local_start.isoformat(),
    }

    first = client.post("/appointments", json=first_data)
    overlapping = client.post(
        "/appointments",
        json={**first_data, "starts_at": (local_start + timedelta(minutes=30)).isoformat()},
    )

    assert first.status_code == 201
    assert overlapping.status_code == 409
    assert Appointment.query.count() == 1


def test_booking_idempotency_and_cancel(client, login_as, tenant_user):
    customer, service, professional = _schedule(tenant_user.company_id)
    login_as(tenant_user)
    local_start = _future_monday(15)
    data = {
        "customer_id": customer.id,
        "service_id": service.id,
        "professional_id": professional.id,
        "starts_at": local_start.isoformat(),
    }
    headers = {"Idempotency-Key": "same-booking"}

    first = client.post("/appointments", json=data, headers=headers)
    repeated = client.post("/appointments", json=data, headers=headers)
    appointment_id = first.get_json()["data"]["id"]

    assert first.status_code == repeated.status_code == 201
    assert repeated.get_json()["data"]["id"] == appointment_id
    assert Appointment.query.count() == 1

    cancelled = client.post(
        f"/appointments/{appointment_id}/cancel", json={"reason": "Cliente pediu"}
    )
    assert cancelled.status_code == 200
    appointment = db.session.get(Appointment, appointment_id)
    assert appointment.status == "CANCELLED"
    assert appointment.cancellation_reason == "Cliente pediu"


def test_company_slot_rules_are_enforced_by_availability_and_create(
    client, login_as, tenant_user
):
    customer, service, professional = _schedule(tenant_user.company_id)
    tenant_user.active_company.settings_json = {
        "slot_interval": 60,
        "minimum_notice_hours": 2,
        "booking_window_days": 30,
    }
    db.session.commit()
    login_as(tenant_user)
    local_start = _future_monday(10)

    availability = client.get(
        "/appointments/availability",
        query_string={
            "service_id": service.id,
            "professional_id": professional.id,
            "date": local_start.date().isoformat(),
        },
    ).get_json()["slots"]
    assert availability
    assert all(int(slot["time"].split(":")[1]) == 0 for slot in availability)

    misaligned = client.post(
        "/appointments",
        json={
            "customer_id": customer.id,
            "service_id": service.id,
            "professional_id": professional.id,
            "starts_at": (local_start + timedelta(minutes=30)).isoformat(),
        },
    )
    too_far = client.post(
        "/appointments",
        json={
            "customer_id": customer.id,
            "service_id": service.id,
            "professional_id": professional.id,
            "starts_at": (local_start + timedelta(days=70)).isoformat(),
        },
    )
    assert misaligned.status_code == too_far.status_code == 409
    assert Appointment.query.count() == 0


def test_schedule_block_uses_company_timezone_and_prevents_booking(
    client, login_as, tenant_user
):
    customer, service, professional = _schedule(tenant_user.company_id)
    login_as(tenant_user)
    local_start = _future_monday(10)

    blocked = client.post(
        "/appointments/blocks",
        json={
            "professional_id": professional.id,
            "title": "Feriado",
            "starts_at": local_start.replace(tzinfo=None).isoformat(),
            "ends_at": (local_start + timedelta(hours=1)).replace(tzinfo=None).isoformat(),
        },
    )
    assert blocked.status_code == 201
    block = ScheduleBlock.query.one()
    assert block.starts_at == local_start.astimezone(timezone.utc).replace(tzinfo=None)

    booking = client.post(
        "/appointments",
        json={
            "customer_id": customer.id,
            "service_id": service.id,
            "professional_id": professional.id,
            "starts_at": local_start.isoformat(),
        },
    )
    assert booking.status_code == 409
    assert Appointment.query.count() == 0
