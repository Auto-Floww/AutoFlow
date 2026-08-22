"""Evolution API v2 client and inbound webhook translator."""

from __future__ import annotations

import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

from flask import current_app, has_app_context

from app.extensions import db
from app.models import WhatsAppIntegration
from app.models.base import utcnow
from app.services.conversation_service import ConversationService
from app.services.customer_service import CustomerService
from app.services.exceptions import ExternalServiceError, ValidationError
from app.services.outbox_service import OutboxService
from app.services.quota_service import QuotaService


INSTANCE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,100}$")


def _setting(name: str, default=None):
    if has_app_context():
        return current_app.config.get(name, os.getenv(name, default))
    return os.getenv(name, default)


class WhatsAppService:
    """Evolution v2 adapter kept behind the existing WhatsApp domain API."""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        self.api_url = str(api_url or _setting("EVOLUTION_API_URL", "")).rstrip("/")
        self.api_key = str(api_key or _setting("EVOLUTION_API_KEY", ""))
        self.timeout = float(timeout or _setting("EVOLUTION_REQUEST_TIMEOUT", 25))

    @staticmethod
    def validate_instance_name(value: str) -> str:
        instance_name = str(value or "").strip()
        if not INSTANCE_NAME_RE.fullmatch(instance_name):
            raise ValidationError(
                "O nome da instancia deve ter entre 3 e 100 caracteres: letras, numeros, _ ou -."
            )
        return instance_name

    def verify_webhook(self, payload: dict[str, Any]) -> bool:
        """Accept Evolution's global key or the token of the emitting instance.

        Evolution v2 emits the per-instance token in ``apikey`` even when REST
        calls made by AutoFlow use the installation-wide key. Validate that
        token against the named instance instead of weakening webhook auth.
        """

        supplied = str(payload.get("apikey") or "")
        if not supplied:
            return False
        if self.api_key and hmac.compare_digest(supplied, self.api_key):
            return True
        instance_name = str(payload.get("instance") or "").strip()
        if not instance_name:
            return False
        try:
            self._request(
                "GET",
                f"instance/connectionState/{urllib.parse.quote(instance_name)}",
                api_key=supplied,
            )
        except ExternalServiceError:
            return False
        return True

    @staticmethod
    def _phone_from_jid(value: str | None) -> str:
        raw = str(value or "").strip()
        if "@" in raw:
            raw = raw.split("@", 1)[0]
        return "".join(character for character in raw if character.isdigit())

    @staticmethod
    def _message_content(message: dict[str, Any]) -> tuple[str, str]:
        field_map = (
            ("conversation", "TEXT", None),
            ("extendedTextMessage", "TEXT", "text"),
            ("imageMessage", "IMAGE", "caption"),
            ("videoMessage", "VIDEO", "caption"),
            ("audioMessage", "AUDIO", None),
            ("documentMessage", "DOCUMENT", "caption"),
            ("locationMessage", "LOCATION", None),
        )
        for field, message_type, text_key in field_map:
            if field not in message:
                continue
            value = message.get(field)
            if isinstance(value, str):
                return value, message_type
            if isinstance(value, dict) and text_key and value.get(text_key):
                return str(value[text_key]), message_type
            if message_type == "LOCATION" and isinstance(value, dict):
                return (
                    f"Localizacao: {value.get('degreesLatitude')}, {value.get('degreesLongitude')}",
                    message_type,
                )
            return f"[{message_type.lower()} recebido]", message_type
        return "[mensagem recebida]", "UNKNOWN"

    @classmethod
    def iter_events(cls, payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        event_name = str(payload.get("event") or "").lower().replace("_", ".")
        if event_name != "messages.upsert":
            return
        instance_name = str(payload.get("instance") or "").strip()
        raw_data = payload.get("data")
        rows = raw_data if isinstance(raw_data, list) else [raw_data]
        for data in rows:
            if not isinstance(data, dict):
                continue
            key = data.get("key") or {}
            if not isinstance(key, dict) or key.get("fromMe"):
                continue
            remote_jid = str(key.get("remoteJid") or "")
            if remote_jid.endswith("@g.us"):
                continue
            sender = cls._phone_from_jid(remote_jid or payload.get("sender"))
            external_message_id = str(key.get("id") or "").strip()
            if not instance_name or not sender or not external_message_id:
                continue
            content, message_type = cls._message_content(data.get("message") or {})
            yield {
                "kind": "message",
                "instance_name": instance_name,
                "external_message_id": external_message_id,
                "from": sender,
                "name": str(data.get("pushName") or "").strip() or None,
                "timestamp": data.get("messageTimestamp") or payload.get("date_time"),
                "message_type": message_type,
                "content": content,
                "payload": data,
            }

    @staticmethod
    def _event_timestamp(value: str | int | float | None):
        if value is None:
            return utcnow()
        try:
            if isinstance(value, str) and "T" in value:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                    timezone.utc
                ).replace(tzinfo=None)
            return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError, OSError):
            return utcnow()

    def process_payload(
        self,
        payload: dict[str, Any],
        *,
        allowed_instances: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        for event in self.iter_events(payload):
            instance_name = event["instance_name"]
            if allowed_instances is not None and instance_name not in allowed_instances:
                raise ValidationError("Webhook fora do escopo da instancia autenticada")
            integration = WhatsAppIntegration.query.filter_by(
                instance_name=instance_name,
                is_active=True,
                status="CONNECTED",
            ).one_or_none()
            if integration is None:
                continue
            company_id = integration.company_id
            existing = QuotaService.enforce_inbound(
                company_id,
                sender=event["from"],
                external_message_id=event["external_message_id"],
            )
            integration.last_webhook_at = self._event_timestamp(event.get("timestamp"))
            if existing is not None:
                db.session.commit()
                processed.append(
                    {
                        "kind": "message",
                        "message_id": existing.id,
                        "conversation_id": existing.conversation_id,
                        "company_id": company_id,
                        "created": False,
                        "new_conversation": False,
                        "outbox_id": None,
                    }
                )
                continue
            customer = CustomerService.upsert_from_whatsapp(
                company_id,
                phone=event["from"],
                name=event.get("name"),
                commit=False,
            )
            conversation, new_conversation = ConversationService.get_or_create(
                company_id,
                customer_id=customer.id,
                channel="WHATSAPP",
                external_id=f"evolution:{instance_name}:{customer.phone_normalized}",
                whatsapp_integration_id=integration.id,
                commit=False,
            )
            message, created = ConversationService.record_inbound(
                company_id,
                conversation_id=conversation.id,
                content=event["content"],
                external_message_id=event["external_message_id"],
                message_type=event["message_type"],
                payload=event["payload"],
                commit=False,
            )
            if new_conversation:
                from app.services.notification_service import NotificationService

                NotificationService.create(
                    company_id,
                    notification_type="NEW_CONVERSATION",
                    title="Nova conversa",
                    body=f"{customer.name} iniciou uma conversa no WhatsApp.",
                    link_url=f"/conversations?conversation={conversation.id}",
                    data={"conversation_id": conversation.id, "customer_id": customer.id},
                    idempotency_key=f"new-conversation:{conversation.id}",
                    commit=False,
                )
            outbox = OutboxService.enqueue(
                "process_message",
                {"message_id": message.id},
                idempotency_key=f"process-message:{message.id}",
                company_id=company_id,
            )
            db.session.commit()
            processed.append(
                {
                    "kind": "message",
                    "message_id": message.id,
                    "conversation_id": conversation.id,
                    "company_id": company_id,
                    "created": created,
                    "new_conversation": new_conversation,
                    "outbox_id": outbox.id,
                }
            )
        return processed

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        request_api_key = str(api_key or self.api_key)
        if not self.api_url or not request_api_key:
            raise ExternalServiceError(
                "Evolution API nao esta configurada", retryable=False
            )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.api_url}/{path.lstrip('/')}",
            data=body,
            headers={
                "apikey": request_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "AutoFlow/1.0",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096).decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
                message = str(detail.get("message") or detail.get("error") or "Evolution request failed")
            except json.JSONDecodeError:
                message = "Evolution request failed"
            raise ExternalServiceError(
                message,
                retryable=exc.code == 429 or exc.code >= 500,
                status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ExternalServiceError(
                "Evolution API esta temporariamente indisponivel", retryable=True
            ) from exc

    def check_connection(
        self, company_id: int, integration_id: int | None = None
    ) -> dict[str, Any]:
        query = WhatsAppIntegration.for_company(company_id)
        if integration_id:
            query = query.filter(WhatsAppIntegration.id == integration_id)
        integration = query.one_or_none()
        if integration is None:
            raise ValidationError("Instancia Evolution nao configurada")
        try:
            result = self._request(
                "GET", f"instance/connectionState/{urllib.parse.quote(integration.instance_name)}"
            )
            state = str((result.get("instance") or {}).get("state") or result.get("state") or "").lower()
            connected = state in {"open", "connected"}
            integration.status = "CONNECTED" if connected else "PENDING"
            integration.is_active = connected
            integration.last_error = None if connected else "A instancia ainda nao esta conectada ao WhatsApp"
            db.session.commit()
            return {
                "connected": connected,
                "integration_id": integration.id,
                "instance_name": integration.instance_name,
                "state": state or "unknown",
            }
        except ExternalServiceError as exc:
            db.session.rollback()
            integration = WhatsAppIntegration.query.filter_by(
                id=integration.id, company_id=int(company_id)
            ).one()
            integration.status = "ERROR"
            integration.is_active = False
            integration.last_error = exc.message[:2000]
            db.session.commit()
            raise

    def request_qr_code(self, instance_name: str) -> dict[str, Any]:
        """Call only the Evolution endpoint that creates/refreshes a QR Code."""

        return self._request(
            "GET", f"instance/connect/{urllib.parse.quote(instance_name)}"
        )

    def create_instance(self, instance_name: str) -> dict[str, Any]:
        """Provision a Baileys instance and ask Evolution for its first QR Code."""

        return self._request(
            "POST",
            "instance/create",
            {
                "instanceName": self.validate_instance_name(instance_name),
                "integration": "WHATSAPP-BAILEYS",
                "qrcode": True,
            },
        )

    def get_instance_state(self, instance_name: str) -> str:
        """Return the normalized connection state from Evolution."""

        result = self._request(
            "GET",
            f"instance/connectionState/{urllib.parse.quote(instance_name)}",
        )
        return str(
            (result.get("instance") or {}).get("state")
            or result.get("state")
            or ""
        ).lower()

    def send_text(
        self,
        company_id: int,
        *,
        to: str,
        text: str,
        integration_id: int | None = None,
        reply_to_external_id: str | None = None,
    ) -> dict[str, Any]:
        query = WhatsAppIntegration.for_company(company_id).filter_by(
            is_active=True, status="CONNECTED"
        )
        if integration_id:
            query = query.filter(WhatsAppIntegration.id == integration_id)
        integration = query.one_or_none()
        if integration is None:
            raise ValidationError("A instancia Evolution nao esta conectada")
        payload: dict[str, Any] = {"number": self._phone_from_jid(to), "text": text[:4096]}
        if reply_to_external_id:
            payload["quoted"] = {"key": {"id": reply_to_external_id}}
        return self._request(
            "POST",
            f"message/sendText/{urllib.parse.quote(integration.instance_name)}",
            payload,
        )

    def disconnect(self, company_id: int) -> None:
        integration = WhatsAppIntegration.for_company(company_id).one_or_none()
        if integration is None:
            raise ValidationError("Instancia Evolution nao configurada")
        try:
            self._request(
                "DELETE", f"instance/logout/{urllib.parse.quote(integration.instance_name)}"
            )
        except ExternalServiceError as exc:
            if exc.external_status != 404:
                raise
        integration.is_active = False
        integration.status = "DISCONNECTED"
        integration.last_error = None
        db.session.commit()
