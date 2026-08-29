"""Use case for resolving eligible delivery options."""

from decimal import Decimal

import app.services.delivery_service as legacy


class GetDeliveryOptionsService:
    def execute(
        self,
        company_id: int,
        *,
        city: str | None = None,
        neighborhood: str | None = None,
        postal_code: str | None = None,
        order_total: str | float | Decimal | None = None,
    ) -> list[dict]:
        return legacy.DeliveryService.options(
            company_id,
            city=city,
            neighborhood=neighborhood,
            postal_code=postal_code,
            order_total=order_total,
        )


__all__ = ["GetDeliveryOptionsService"]
