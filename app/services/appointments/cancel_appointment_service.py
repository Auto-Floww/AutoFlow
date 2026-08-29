"""Use case for cancelling an appointment."""

import app.services.appointment_service as legacy


class CancelAppointmentService:
    def execute(
        self,
        company_id: int,
        appointment_id: int,
        *,
        reason: str | None = None,
        commit: bool = True,
    ):
        return legacy.AppointmentService.cancel(
            company_id,
            appointment_id,
            reason=reason,
            commit=commit,
        )


__all__ = ["CancelAppointmentService"]
