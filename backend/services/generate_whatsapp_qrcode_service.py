"""Use case: generate a QR Code for one WhatsApp integration."""

from __future__ import annotations

import base64
import binascii

from app.services.exceptions import ExternalServiceError, ValidationError
from app.services.whatsapp_service import WhatsAppService
from backend.models import WhatsAppIntegration


class GenerateWhatsAppQrCodeService:
    """Validate and coordinate only the QR Code generation use case."""

    def __init__(self, evolution_service: WhatsAppService | None = None):
        self.evolution_service = evolution_service or WhatsAppService()

    def execute(self, company_id: int) -> dict:
        integration = WhatsAppIntegration.for_company(company_id).one_or_none()
        if integration is None:
            raise ValidationError("Salve o nome da instancia antes de gerar o QR Code")

        try:
            result = self.evolution_service.request_qr_code(integration.instance_name)
        except ExternalServiceError as exc:
            if exc.external_status != 404:
                raise
            # A configuracao do AutoFlow pode ser salva antes de a instancia
            # existir na Evolution. Provisione-a no primeiro pedido de QR Code
            # para que esse estado esperado nao seja exposto como um 502.
            result = self.evolution_service.create_instance(integration.instance_name)
        qrcode = result.get("qrcode") if isinstance(result.get("qrcode"), dict) else {}
        value = result.get("base64") or qrcode.get("base64")
        pairing_code = result.get("pairingCode") or qrcode.get("pairingCode")

        if not value:
            state = self.evolution_service.get_instance_state(
                integration.instance_name
            )
            if state in {"open", "connected"}:
                return {
                    "connected": True,
                    "instance_name": integration.instance_name,
                    "state": state,
                }
            raise ExternalServiceError(
                "A Evolution API ainda nao disponibilizou o QR Code. Tente atualizar em alguns segundos.",
                retryable=True,
            )

        encoded = self._validated_png(value)
        return {
            "connected": False,
            "instance_name": integration.instance_name,
            "qr_code": f"data:image/png;base64,{encoded}",
            "pairing_code": str(pairing_code).strip() if pairing_code else None,
        }

    @staticmethod
    def _validated_png(value) -> str:
        encoded = str(value).strip()
        if encoded.startswith("data:"):
            prefix, separator, encoded = encoded.partition(",")
            if not separator or prefix.lower() != "data:image/png;base64":
                raise ExternalServiceError(
                    "A Evolution API retornou um QR Code em formato invalido",
                    retryable=False,
                )
        if not encoded or len(encoded) > 2_000_000:
            raise ExternalServiceError(
                "A Evolution API retornou um QR Code em formato invalido",
                retryable=False,
            )
        try:
            image = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ExternalServiceError(
                "A Evolution API retornou um QR Code em formato invalido",
                retryable=False,
            ) from exc
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ExternalServiceError(
                "A Evolution API retornou um QR Code em formato invalido",
                retryable=False,
            )
        return encoded
