"""Webhook oficial da WhatsApp Cloud API (Meta)."""

from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request

from app.extensions import csrf, db, limiter
from app.models import WhatsAppIntegration
from app.services.exceptions import DomainError, RateLimitError
from app.services.outbox_service import OutboxService
from app.services.whatsapp_service import WhatsAppService


bp = Blueprint("whatsapp", __name__)


def _phone_number_ids(data: dict) -> set[str]:
    return {
        str(event["phone_number_id"])
        for event in WhatsAppService.iter_events(data)
        if event.get("phone_number_id")
    }


@bp.get("/webhooks/whatsapp")
@csrf.exempt
@limiter.limit("60 per minute")
def webhook_verify():
    try:
        challenge = WhatsAppService().verify_challenge(
            request.args.get("hub.mode", ""),
            request.args.get("hub.verify_token", ""),
            request.args.get("hub.challenge", ""),
        )
    except DomainError:
        return Response("Verification failed", status=403, mimetype="text/plain")
    return Response(challenge, status=200, mimetype="text/plain")


@bp.post("/webhooks/whatsapp")
@csrf.exempt
@limiter.limit("600 per minute")
def webhook():
    raw_body = request.get_data(cache=True)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid_payload"), 400

    phone_number_ids = _phone_number_ids(data)
    integrations = (
        WhatsAppIntegration.query.filter(
            WhatsAppIntegration.phone_number_id.in_(phone_number_ids),
            WhatsAppIntegration.is_active.is_(True),
            WhatsAppIntegration.status == "CONNECTED",
        ).all()
        if phone_number_ids
        else []
    )
    # Um POST Meta possui uma única assinatura. Aceitar changes de empresas
    # diferentes permitiria que o segredo de uma integração autorizasse outra.
    if len(integrations) != len(phone_number_ids) or len(
        {integration.company_id for integration in integrations}
    ) > 1:
        current_app.logger.warning(
            "Webhook WhatsApp referencia integracoes desconhecidas ou multi-tenant"
        )
        return jsonify(error="invalid_integration_scope"), 400

    service = WhatsAppService()
    signature = request.headers.get("X-Hub-Signature-256")
    try:
        valid_signature = (
            all(
                service.verify_signature(
                    raw_body, signature, integration=integration
                )
                for integration in integrations
            )
            if integrations
            else service.verify_signature(raw_body, signature)
        )
    except DomainError:
        current_app.logger.exception("Credencial Meta invalida no webhook")
        return jsonify(error="integration_configuration_error"), 503
    if not valid_signature:
        current_app.logger.warning("Webhook WhatsApp com assinatura invalida")
        return jsonify(error="invalid_signature"), 401

    try:
        events = service.process_payload(
            data, allowed_phone_number_ids=phone_number_ids
        )
    except RateLimitError as exc:
        # Release the tenant capacity lock and discard every mutation belonging
        # to the rejected inbound before reporting backpressure to Meta.
        db.session.rollback()
        response = jsonify(exc.to_dict())
        response.status_code = exc.status_code
        response.headers["Retry-After"] = str(exc.retry_after)
        return response
    except DomainError as exc:
        db.session.rollback()
        current_app.logger.warning("Webhook WhatsApp rejeitado: %s", exc.message)
        return jsonify(error=exc.code), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Falha ao persistir webhook WhatsApp")
        return jsonify(error="processing_error"), 500

    # Message and outbox were committed atomically by the service. Redis is only
    # a best-effort optimization here; Celery beat recovers every pending row.
    queued = 0
    outbox_pending = 0
    for event in events:
        if event.get("kind") != "message" or not event.get("outbox_id"):
            continue
        dispatched = OutboxService.dispatch_best_effort(event["outbox_id"])
        if dispatched:
            queued += 1
        else:
            outbox_pending += 1
    return jsonify(
        received=True,
        events=len(events),
        queued=queued,
        outbox_pending=outbox_pending,
    ), 200
