"""Use case for dispatching one transactional-outbox entry."""

import app.services.outbox_service as legacy


class DispatchOutboxEntryService:
    def execute(self, entry_id: int) -> bool:
        return legacy.OutboxService.dispatch_one(entry_id)


__all__ = ["DispatchOutboxEntryService"]
