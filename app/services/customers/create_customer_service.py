"""Use case for creating a customer."""

import app.services.customer_service as legacy


class CreateCustomerService:
    def execute(
        self,
        company_id: int,
        *,
        name: str,
        phone: str,
        email: str | None = None,
        organization: str | None = None,
        notes: str | None = None,
        source: str = "MANUAL",
        commit: bool = True,
    ):
        return legacy.CustomerService.create(
            company_id,
            name=name,
            phone=phone,
            email=email,
            organization=organization,
            notes=notes,
            source=source,
            commit=commit,
        )


__all__ = ["CreateCustomerService"]
