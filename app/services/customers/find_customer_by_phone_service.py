"""Use case for finding a customer by normalized phone."""

import app.services.customer_service as legacy


class FindCustomerByPhoneService:
    def execute(self, company_id: int, phone: str):
        return legacy.CustomerService.find_by_phone(company_id, phone)


__all__ = ["FindCustomerByPhoneService"]
