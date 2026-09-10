"""Configuração do Blueprint do webhook do WhatsApp e exportação do handler para compatibilidade.."""

from app.controllers.whatsapp_controller import WhatsAppController, bp

evolution_webhook = WhatsAppController.evolution_webhook

__all__ = ["WhatsAppController", "bp", "evolution_webhook"]
