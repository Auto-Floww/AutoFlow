"""AutoFlow persistence models.

Importing this package registers every mapper with Flask-SQLAlchemy.
"""

from app.models.appointment import (
    Appointment,
    BusinessHour,
    Professional,
    ScheduleBlock,
    Service,
    professional_services,
)
from app.models.audit import AuditLog
from app.models.company import Company, CompanyMember
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.delivery import DeliveryRule
from app.models.inventory import Inventory, InventoryMovement
from app.models.knowledge import FAQ, KnowledgeDocument
from app.models.message import Message
from app.models.notification import Notification
from app.models.outbox import TaskOutbox
from app.models.product import Product, ProductVariant
from app.models.settings import AISettings, WhatsAppIntegration
from app.models.tag import ConversationTag, CustomerTag, Tag
from app.models.user import User

__all__ = [
    "AISettings",
    "Appointment",
    "AuditLog",
    "BusinessHour",
    "Company",
    "CompanyMember",
    "Conversation",
    "ConversationTag",
    "Customer",
    "CustomerTag",
    "DeliveryRule",
    "FAQ",
    "Inventory",
    "InventoryMovement",
    "KnowledgeDocument",
    "Message",
    "Notification",
    "Product",
    "ProductVariant",
    "Professional",
    "ScheduleBlock",
    "Service",
    "Tag",
    "TaskOutbox",
    "User",
    "WhatsAppIntegration",
    "professional_services",
]
