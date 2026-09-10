"""Casos de uso de agendamentos, com uma classe de serviço por módulo."""

from app.services.appointments.cancel_appointment_service import CancelAppointmentService
from app.services.appointments.create_appointment_service import CreateAppointmentService
from app.services.appointments.get_appointment_service import GetAppointmentService
from app.services.appointments.get_available_appointments_service import (
    GetAvailableAppointmentsService,
)

__all__ = [
    "CancelAppointmentService",
    "CreateAppointmentService",
    "GetAppointmentService",
    "GetAvailableAppointmentsService",
]
