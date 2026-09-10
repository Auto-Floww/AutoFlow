"""Caso de uso para buscar um agendamento específico pertencente a um determinado tenant (cliente ou organização)."""

import app.services.appointment_service as legacy


class GetAppointmentService:
    def execute(self, company_id: int, appointment_id: int):
        return legacy.AppointmentService.get(company_id, appointment_id)


__all__ = ["GetAppointmentService"]
