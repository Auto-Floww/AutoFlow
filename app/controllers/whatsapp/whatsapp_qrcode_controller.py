"""Controller para o recurso de código QR do WhatsApp."""

from __future__ import annotations

from flask import Blueprint, jsonify
from flask_login import login_required

from app.controllers.http import failure
from app.services.exceptions import DomainError
from app.services.whatsapp.generate_whatsapp_qrcode_service import (
    GenerateWhatsAppQrCodeService,
)
from app.tenant import current_company_id, roles_required


whatsapp_qrcode_bp = Blueprint(
    "whatsapp_qrcode_controller", __name__, url_prefix="/settings/whatsapp"
)


class WhatsAppQrCodeController:
    """Receive HTTP input, invoke the use case, and serialize its result."""

    def __init__(self, service_factory=GenerateWhatsAppQrCodeService):
        self.service_factory = service_factory

    def create(self):
        try:
            result = self.service_factory().execute(current_company_id())
        except DomainError as exc:
            return failure(exc.message, status=exc.status_code)
        message = (
            "Esta instancia ja esta conectada."
            if result.get("connected")
            else "QR Code atualizado."
        )
        response = jsonify(ok=True, message=message, data=result)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


_controller = WhatsAppQrCodeController()
whatsapp_qrcode_bp.add_url_rule(
    "/qrcode",
    endpoint="create",
    view_func=login_required(
        roles_required("ADMIN", "OWNER")(_controller.create)
    ),
    methods=["POST"],
)
