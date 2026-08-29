"""Use case for archiving a tenant-scoped customer."""

from app.extensions import db
from app.models import Customer
from app.services.tenancy import tenant_get


class ArchiveCustomerService:
    def execute(
        self,
        company_id: int,
        customer_id: int,
        commit: bool = True,
    ) -> Customer:
        customer = tenant_get(Customer, company_id, customer_id, lock=True)
        customer.status = "INACTIVE"
        if commit:
            db.session.commit()
        return customer


__all__ = ["ArchiveCustomerService"]
