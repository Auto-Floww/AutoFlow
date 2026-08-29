"""Settings Blueprint wiring and compatibility handler exports."""

from app.controllers.settings_controller import SettingsController, bp

ai = SettingsController.ai
save_ai = SettingsController.save_ai
whatsapp = SettingsController.whatsapp
save_whatsapp = SettingsController.save_whatsapp
check_whatsapp = SettingsController.check_whatsapp
test_whatsapp = SettingsController.test_whatsapp
disconnect_whatsapp = SettingsController.disconnect_whatsapp

__all__ = [
    "SettingsController",
    "ai",
    "bp",
    "check_whatsapp",
    "disconnect_whatsapp",
    "save_ai",
    "save_whatsapp",
    "test_whatsapp",
    "whatsapp",
]
