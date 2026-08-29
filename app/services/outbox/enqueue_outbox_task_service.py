"""Use case for persisting an allow-listed task intent."""

from typing import Any

import app.services.outbox_service as legacy


class EnqueueOutboxTaskService:
    def execute(
        self,
        task_name: str,
        payload: dict[str, Any] | None,
        *,
        idempotency_key: str,
        company_id: int | None = None,
        available_at=None,
    ):
        return legacy.OutboxService.enqueue(
            task_name,
            payload,
            idempotency_key=idempotency_key,
            company_id=company_id,
            available_at=available_at,
        )


__all__ = ["EnqueueOutboxTaskService"]
