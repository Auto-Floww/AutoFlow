"""Use case for updating a customer profile or CRM state."""

from typing import Any

import app.services.customer_service as legacy


class UpdateCustomerService:
    def execute(
        self,
        company_id: int,
        customer_id: int,
        *,
        commit: bool = True,
        **changes: Any,
    ):
        return legacy.CustomerService.update(
            company_id,
            customer_id,
            commit=commit,
            **changes,
        )


__all__ = ["UpdateCustomerService"]
