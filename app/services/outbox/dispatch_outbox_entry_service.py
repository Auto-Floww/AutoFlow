"""Caso de uso para enviar uma entrada da caixa de saída transacional."""

import app.services.outbox_service as legacy


class DispatchOutboxEntryService:
    def execute(self, entry_id: int) -> bool:
        return legacy.OutboxService.dispatch_one(entry_id)


__all__ = ["DispatchOutboxEntryService"]
