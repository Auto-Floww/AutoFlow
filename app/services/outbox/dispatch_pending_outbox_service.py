"""Use case for dispatching a bounded batch of pending outbox entries."""

import app.services.outbox_service as legacy


class DispatchPendingOutboxService:
    def execute(self, *, limit: int | None = None) -> dict[str, int]:
        return legacy.OutboxService.dispatch_pending(limit=limit)


__all__ = ["DispatchPendingOutboxService"]
