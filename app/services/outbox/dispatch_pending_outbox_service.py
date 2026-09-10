"""Caso de uso para enviar um lote limitado de entradas pendentes da caixa de saída."""

import app.services.outbox_service as legacy


class DispatchPendingOutboxService:
    def execute(self, *, limit: int | None = None) -> dict[str, int]:
        return legacy.OutboxService.dispatch_pending(limit=limit)


__all__ = ["DispatchPendingOutboxService"]
