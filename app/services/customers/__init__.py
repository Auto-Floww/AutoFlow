"""Customer and CRM use cases."""

from app.services.customers.add_customer_tag_service import AddCustomerTagService
from app.services.customers.archive_customer_service import ArchiveCustomerService
from app.services.customers.create_customer_service import CreateCustomerService
from app.services.customers.find_customer_by_phone_service import FindCustomerByPhoneService
from app.services.customers.get_customer_service import GetCustomerService
from app.services.customers.list_customers_service import ListCustomersService
from app.services.customers.update_customer_service import UpdateCustomerService
from app.services.customers.upsert_customer_from_whatsapp_service import (
    UpsertCustomerFromWhatsAppService,
)

__all__ = [
    "AddCustomerTagService",
    "ArchiveCustomerService",
    "CreateCustomerService",
    "FindCustomerByPhoneService",
    "GetCustomerService",
    "ListCustomersService",
    "UpdateCustomerService",
    "UpsertCustomerFromWhatsAppService",
]
