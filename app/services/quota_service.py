"""Transactional inbound quotas that protect downstream AI capacity and cost."""

from __future__ import annotations

import os
from datetime import timedelta

from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models import Company, Customer, Message
from app.models.base import utcnow
from app.services.customer_service import normalize_phone
from app.services.exceptions import RateLimitError, ValidationError


DEFAULT_INBOUND_HOURLY_LIMIT = 300
DEFAULT_SENDER_MINUTE_LIMIT = 30


def _positive_setting(name: str, default: int) -> int:
    configured = current_app.config.get(name)
    if configured is None:
        configured = os.getenv(name, default)
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        current_app.logger.warning(
            "Configuracao %s invalida; usando limite padrao", name
        )
        return default


class InboundQuotaPolicy:
    """Serialize check-and-insert capacity per company using its database row."""

    @staticmethod
    def enforce_inbound(
        company_id: int,
        *,
        sender: str,
        external_message_id: str,
    ) -> Message | None:
        """Return an existing duplicate or reserve capacity for a new inbound.

        The caller must create the new ``Message`` and commit it in the same
        transaction. The company row lock remains held until that commit, making
        the count plus insert atomic with respect to other webhook workers.
        """

        company_id = int(company_id)
        external_message_id = str(external_message_id or "").strip()
        if not external_message_id:
            raise ValidationError("External message ID is required")

        # Fast idempotency path: retries already stored by Meta never consume
        # quota and do not contend on the tenant-wide capacity lock.
        existing = Message.query.filter_by(
            company_id=company_id,
            external_message_id=external_message_id,
        ).one_or_none()
        if existing is not None:
            return existing

        normalized_sender = normalize_phone(sender)
        company = (
            Company.query.filter(Company.id == company_id)
            .with_for_update()
            .one_or_none()
        )
        if company is None:
            raise ValidationError("Webhook company is invalid")

        # A concurrent retry can have committed while this worker waited for the
        # company lock, so idempotency must be checked again under the lock.
        existing = Message.query.filter_by(
            company_id=company_id,
            external_message_id=external_message_id,
        ).one_or_none()
        if existing is not None:
            return existing

        now = utcnow()
        hourly_limit = _positive_setting(
            "AI_INBOUND_HOURLY_LIMIT", DEFAULT_INBOUND_HOURLY_LIMIT
        )
        hourly_count = (
            db.session.query(func.count(Message.id))
            .filter(
                Message.company_id == company_id,
                Message.direction == "INBOUND",
                Message.created_at >= now - timedelta(hours=1),
            )
            .scalar()
            or 0
        )
        if hourly_count >= hourly_limit:
            raise RateLimitError(
                "Company inbound hourly quota exceeded",
                retry_after=3600,
                scope="company_hour",
                limit=hourly_limit,
            )

        customer_id = (
            db.session.query(Customer.id)
            .filter(
                Customer.company_id == company_id,
                Customer.phone_normalized == normalized_sender,
            )
            .scalar()
        )
        if customer_id is not None:
            sender_limit = _positive_setting(
                "AI_SENDER_MINUTE_LIMIT", DEFAULT_SENDER_MINUTE_LIMIT
            )
            sender_count = (
                db.session.query(func.count(Message.id))
                .filter(
                    Message.company_id == company_id,
                    Message.customer_id == customer_id,
                    Message.direction == "INBOUND",
                    Message.created_at >= now - timedelta(minutes=1),
                )
                .scalar()
                or 0
            )
            if sender_count >= sender_limit:
                raise RateLimitError(
                    "Sender inbound minute quota exceeded",
                    retry_after=60,
                    scope="sender_minute",
                    limit=sender_limit,
                )

        return None


# Backwards-compatible alias; the use case is ``EnforceInboundQuotaService``.
QuotaService = InboundQuotaPolicy
