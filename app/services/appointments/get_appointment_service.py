"""Use case for retrieving one tenant-scoped appointment."""

import app.services.appointment_service as legacy


class GetAppointmentService:
    def execute(self, company_id: int, appointment_id: int):
        return legacy.AppointmentService.get(company_id, appointment_id)


__all__ = ["GetAppointmentService"]
