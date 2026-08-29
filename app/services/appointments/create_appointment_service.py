"""Use case for creating an appointment transactionally."""

from datetime import datetime

import app.services.appointment_service as legacy


class CreateAppointmentService:
    def execute(
        self,
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
    ):
        return legacy.AppointmentService.create(
            company_id,
            customer_id=customer_id,
            service_id=service_id,
            professional_id=professional_id,
            starts_at=starts_at,
            notes=notes,
            created_by_user_id=created_by_user_id,
            idempotency_key=idempotency_key,
            external_reference=external_reference,
            commit=commit,
        )


__all__ = ["CreateAppointmentService"]
