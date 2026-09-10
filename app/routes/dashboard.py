"""Configuração do Blueprint do painel de controle e exportações de handlers para compatibilidade."""

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
