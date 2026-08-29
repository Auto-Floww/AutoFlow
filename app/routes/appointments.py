"""Appointment Blueprint wiring and backwards-compatible handler exports."""

from app.controllers.appointments_controller import AppointmentsController, bp

index = AppointmentsController.index
availability = AppointmentsController.availability
create = AppointmentsController.create
cancel = AppointmentsController.cancel
create_service = AppointmentsController.create_service
create_professional = AppointmentsController.create_professional
save_business_hour = AppointmentsController.save_business_hour
create_block = AppointmentsController.create_block
delete_block = AppointmentsController.delete_block
confirm = AppointmentsController.confirm
delete_service = AppointmentsController.delete_service
save_settings = AppointmentsController.save_settings

__all__ = [
    "AppointmentsController",
    "availability",
    "bp",
    "cancel",
    "confirm",
    "create",
    "create_block",
    "create_professional",
    "create_service",
    "delete_block",
    "delete_service",
    "index",
    "save_business_hour",
    "save_settings",
]
