"""Use case for attaching a tenant-scoped tag to a customer."""

import app.services.customer_service as legacy


class AddCustomerTagService:
    def execute(
        self,
        company_id: int,
        customer_id: int,
        *,
        tag_id: int | None = None,
        tag_name: str | None = None,
        color: str = "#6D5DFB",
        commit: bool = True,
    ):
        return legacy.CustomerService.add_tag(
            company_id,
            customer_id,
            tag_id=tag_id,
            tag_name=tag_name,
            color=color,
            commit=commit,
        )


__all__ = ["AddCustomerTagService"]
