"""WhatsApp webhook Blueprint wiring and compatibility handler export."""

from app.controllers.whatsapp_controller import WhatsAppController, bp

evolution_webhook = WhatsAppController.evolution_webhook

__all__ = ["WhatsAppController", "bp", "evolution_webhook"]
