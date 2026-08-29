"""Use case for attempting immediate outbox dispatch safely."""

import app.services.outbox_service as legacy


class DispatchOutboxBestEffortService:
    def execute(self, entry_id: int) -> bool:
        return legacy.OutboxService.dispatch_best_effort(entry_id)


__all__ = ["DispatchOutboxBestEffortService"]
