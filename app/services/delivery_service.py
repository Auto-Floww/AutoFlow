"""Deterministic delivery rule matching."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.models import DeliveryRule
from app.services.exceptions import ValidationError


def _digits(value: str | None) -> str:
    return "".join(character for character in (value or "") if character.isdigit())


class DeliveryService:
    @staticmethod
    def options(
        company_id: int,
        *,
        city: str | None = None,
        neighborhood: str | None = None,
        postal_code: str | None = None,
        order_total: str | float | Decimal | None = None,
    ) -> list[dict]:
        try:
            total = Decimal(str(order_total or 0))
        except InvalidOperation as exc:
            raise ValidationError("Invalid order total") from exc
        normalized_city = (city or "").strip().casefold()
        normalized_neighborhood = (neighborhood or "").strip().casefold()
        postal = _digits(postal_code)
        matches: list[tuple[int, DeliveryRule]] = []
        for rule in DeliveryRule.for_company(company_id).filter_by(is_active=True).all():
            score = 0
            if normalized_city and rule.city:
                if rule.city.strip().casefold() != normalized_city:
                    continue
                score += 10
            if normalized_neighborhood and rule.neighborhood:
                if rule.neighborhood.strip().casefold() != normalized_neighborhood:
                    continue
                score += 20
            if postal and (rule.postal_code_start or rule.postal_code_end):
                start = _digits(rule.postal_code_start) or "0"
                end = _digits(rule.postal_code_end) or "9" * 8
                if not start <= postal <= end:
                    continue
                score += 30
            matches.append((score, rule))
        matches.sort(key=lambda entry: (-entry[0], entry[1].priority, entry[1].id))
        return [
            {
                "id": rule.id,
                "name": rule.name,
                "price": str(Decimal("0.00") if rule.free_shipping else rule.price),
                "free_shipping": rule.free_shipping,
                "eligible": total >= rule.minimum_order,
                "minimum_order": str(rule.minimum_order),
                "min_delivery_days": rule.min_delivery_days,
                "max_delivery_days": rule.max_delivery_days,
                "pickup_available": rule.pickup_available,
            }
            for _, rule in matches
        ]
