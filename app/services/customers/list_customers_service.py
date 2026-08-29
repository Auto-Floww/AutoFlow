"""Use case for listing and filtering tenant customers."""

import app.services.customer_service as legacy


class ListCustomersService:
    def execute(
        self,
        company_id: int,
        *,
        search: str | None = None,
        stage: str | None = None,
        status: str | None = None,
    ):
        return legacy.CustomerService.list(
            company_id,
            search=search,
            stage=stage,
            status=status,
        )


__all__ = ["ListCustomersService"]
