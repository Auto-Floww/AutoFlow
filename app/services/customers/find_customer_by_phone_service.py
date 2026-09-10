"""Caso de uso para localizar um cliente pelo número de telefone normalizado."""

import app.services.customer_service as legacy


class FindCustomerByPhoneService:
    def execute(self, company_id: int, phone: str):
        return legacy.CustomerService.find_by_phone(company_id, phone)


__all__ = ["FindCustomerByPhoneService"]
