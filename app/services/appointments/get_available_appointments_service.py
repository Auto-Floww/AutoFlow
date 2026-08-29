"""Use case for listing bookable appointment slots."""

from datetime import date

import app.services.appointment_service as legacy


class GetAvailableAppointmentsService:
    def execute(
        self,
        company_id: int,
        *,
        service_id: int,
        day: date | str,
        professional_id: int | None = None,
        step_minutes: int | None = None,
        limit: int = 30,
    ) -> list[dict]:
        return legacy.AppointmentService.available_slots(
            company_id,
            service_id=service_id,
            day=day,
            professional_id=professional_id,
            step_minutes=step_minutes,
            limit=limit,
        )


__all__ = ["GetAvailableAppointmentsService"]
