"""Caso de uso para tentar enviar imediatamente um item da caixa de saída, de forma segura."""

import app.services.outbox_service as legacy


class DispatchOutboxBestEffortService:
    def execute(self, entry_id: int) -> bool:
        return legacy.OutboxService.dispatch_best_effort(entry_id)


__all__ = ["DispatchOutboxBestEffortService"]
