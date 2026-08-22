"""WhatsApp integration domain model.

The SQLAlchemy mapping remains in ``app.models`` for compatibility with the
existing application. This module is the explicit domain boundary used by new
backend use cases.
"""

from app.models import WhatsAppIntegration

__all__ = ["WhatsAppIntegration"]
