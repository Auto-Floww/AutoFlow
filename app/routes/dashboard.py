"""Dashboard Blueprint wiring and compatibility handler exports."""

from app.controllers.dashboard_controller import DashboardController, bp

index = DashboardController.index
metrics = DashboardController.metrics
read_notification = DashboardController.read_notification

__all__ = [
    "DashboardController",
    "bp",
    "index",
    "metrics",
    "read_notification",
]
