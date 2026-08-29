"""Use case for upserting a customer received from WhatsApp."""

import app.services.customer_service as legacy


class UpsertCustomerFromWhatsAppService:
    def execute(
        self,
        company_id: int,
        *,
        phone: str,
        name: str | None = None,
        commit: bool = True,
    ):
        return legacy.CustomerService.upsert_from_whatsapp(
            company_id,
            phone=phone,
            name=name,
            commit=commit,
        )


__all__ = ["UpsertCustomerFromWhatsAppService"]
