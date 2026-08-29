"""Use case for retrieving one tenant-scoped customer."""

import app.services.customer_service as legacy


class GetCustomerService:
    def execute(self, company_id: int, customer_id: int):
        return legacy.CustomerService.get(company_id, customer_id)


__all__ = ["GetCustomerService"]
