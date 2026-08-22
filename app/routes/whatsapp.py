"""Evolution API v2 webhook endpoint."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.extensions import csrf, db, limiter
from app.services.exceptions import DomainError, RateLimitError
from app.services.outbox_service import OutboxService
from app.services.whatsapp_service import WhatsAppService


bp = Blueprint("whatsapp", __name__)


@bp.post("/webhooks/evolution")
@csrf.exempt
@limiter.limit("600 per minute")
def evolution_webhook():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid_payload"), 400

    service = WhatsAppService()
    if not service.verify_webhook(data):
        current_app.logger.warning("Webhook Evolution com chave invalida")
        return jsonify(error="invalid_api_key"), 401

    instance_name = str(data.get("instance") or "").strip()
    if not instance_name:
        return jsonify(error="invalid_instance"), 400
    try:
        events = service.process_payload(data, allowed_instances={instance_name})
    except RateLimitError as exc:
        db.session.rollback()
        response = jsonify(exc.to_dict())
        response.status_code = exc.status_code
        response.headers["Retry-After"] = str(exc.retry_after)
        return response
    except DomainError as exc:
        db.session.rollback()
        current_app.logger.warning("Webhook Evolution rejeitado: %s", exc.message)
        return jsonify(error=exc.code), exc.status_code
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Falha ao persistir webhook Evolution")
        return jsonify(error="processing_error"), 500

    queued = 0
    outbox_pending = 0
    for event in events:
        if event.get("kind") != "message" or not event.get("outbox_id"):
            continue
        if OutboxService.dispatch_best_effort(event["outbox_id"]):
            queued += 1
        else:
            outbox_pending += 1
    return jsonify(
        received=True,
        events=len(events),
        queued=queued,
        outbox_pending=outbox_pending,
    ), 200
