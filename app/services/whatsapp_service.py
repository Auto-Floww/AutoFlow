"""Official Meta WhatsApp Cloud API client and webhook parser."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from flask import current_app, has_app_context

from app.extensions import db
from app.models import Message, WhatsAppIntegration
from app.models.base import utcnow
from app.security import decrypt_secret, encrypt_secret
from app.services.conversation_service import ConversationService
from app.services.customer_service import CustomerService
from app.services.exceptions import ExternalServiceError, ValidationError
from app.services.outbox_service import OutboxService
from app.services.quota_service import QuotaService


def _setting(name: str, default=None):
    if has_app_context():
        return current_app.config.get(name, os.getenv(name, default))
    return os.getenv(name, default)


class WhatsAppService:
    def __init__(
        self,
        *,
        access_token: str | None = None,
        app_secret: str | None = None,
        verify_token: str | None = None,
        api_version: str | None = None,
        timeout: int = 25,
        credential_resolver: Callable[[WhatsAppIntegration, str], str | None] | None = None,
    ):
        self.access_token = access_token or _setting("WHATSAPP_ACCESS_TOKEN")
        self.app_secret = app_secret or _setting("WHATSAPP_APP_SECRET")
        self.verify_token = verify_token or _setting("WHATSAPP_VERIFY_TOKEN")
        self.api_version = api_version or _setting(
            "WHATSAPP_API_VERSION", _setting("META_GRAPH_VERSION", "v21.0")
        )
        self.timeout = timeout
        self.credential_resolver = credential_resolver

    def verify_challenge(self, mode: str, token: str, challenge: str) -> str:
        if mode != "subscribe" or not self.verify_token:
            raise ValidationError("Webhook verification failed")
        if not hmac.compare_digest(str(token or ""), str(self.verify_token)):
            raise ValidationError("Webhook verification failed")
        return challenge

    def verify_signature(
        self,
        raw_body: bytes,
        signature_header: str | None,
        *,
        integration: WhatsAppIntegration | None = None,
    ) -> bool:
        secret = (
            self._credential(integration, "app_secret") if integration else self.app_secret
        )
        if not secret or not signature_header:
            return False
        try:
            algorithm, supplied = signature_header.split("=", 1)
        except ValueError:
            return False
        if algorithm.lower() != "sha256":
            return False
        expected = hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(supplied.lower(), expected.lower())

    def verify_payload_signature(
        self,
        raw_body: bytes,
        signature_header: str | None,
        payload: dict[str, Any],
    ) -> bool:
        """Resolve a tenant key from the untrusted payload, then authenticate it."""

        phone_number_id = next(
            (
                event.get("phone_number_id")
                for event in self.iter_events(payload)
                if event.get("phone_number_id")
            ),
            None,
        )
        integration = (
            WhatsAppIntegration.query.filter_by(
                phone_number_id=phone_number_id,
                is_active=True,
                status="CONNECTED",
            ).one_or_none()
            if phone_number_id
            else None
        )
        return self.verify_signature(
            raw_body, signature_header, integration=integration
        )

    @staticmethod
    def _message_content(message: dict[str, Any]) -> tuple[str, str]:
        message_type = (message.get("type") or "unknown").upper()
        if message_type == "TEXT":
            return message.get("text", {}).get("body", ""), message_type
        if message_type == "BUTTON":
            return message.get("button", {}).get("text", ""), message_type
        if message_type == "INTERACTIVE":
            interactive = message.get("interactive") or {}
            selection = interactive.get("button_reply") or interactive.get("list_reply") or {}
            return selection.get("title") or selection.get("id") or "", message_type
        if message_type in {"IMAGE", "VIDEO", "AUDIO", "DOCUMENT"}:
            media = message.get(message_type.lower()) or {}
            return media.get("caption") or f"[{message_type.lower()} recebido]", message_type
        if message_type == "LOCATION":
            location = message.get("location") or {}
            return (
                f"Localização: {location.get('latitude')}, {location.get('longitude')}",
                message_type,
            )
        return f"[{message_type.lower()} recebido]", message_type

    @classmethod
    def iter_events(cls, payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        if payload.get("object") != "whatsapp_business_account":
            return
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                if change.get("field") != "messages":
                    continue
                value = change.get("value") or {}
                phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
                contacts = {
                    contact.get("wa_id"): (contact.get("profile") or {}).get("name")
                    for contact in value.get("contacts") or []
                }
                for message in value.get("messages") or []:
                    content, message_type = cls._message_content(message)
                    yield {
                        "kind": "message",
                        "phone_number_id": phone_number_id,
                        "external_message_id": message.get("id"),
                        "from": message.get("from"),
                        "name": contacts.get(message.get("from")),
                        "timestamp": message.get("timestamp"),
                        "message_type": message_type,
                        "content": content,
                        "payload": message,
                    }
                for status in value.get("statuses") or []:
                    yield {
                        "kind": "status",
                        "phone_number_id": phone_number_id,
                        "external_message_id": status.get("id"),
                        "status": status.get("status"),
                        "timestamp": status.get("timestamp"),
                        "errors": status.get("errors") or [],
                    }

    @staticmethod
    def _event_timestamp(value: str | int | None):
        if value is None:
            return utcnow()
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError, OSError):
            return utcnow()

    def process_payload(
        self,
        payload: dict[str, Any],
        *,
        allowed_phone_number_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        status_map = {"sent": "SENT", "delivered": "DELIVERED", "read": "READ", "failed": "FAILED"}
        for event in self.iter_events(payload):
            phone_number_id = str(event.get("phone_number_id") or "")
            if (
                allowed_phone_number_ids is not None
                and phone_number_id not in allowed_phone_number_ids
            ):
                raise ValidationError("Webhook event is outside the authenticated scope")
            integration = WhatsAppIntegration.query.filter_by(
                phone_number_id=phone_number_id,
                is_active=True,
                status="CONNECTED",
            ).one_or_none()
            if integration is None:
                continue
            company_id = integration.company_id
            if event["kind"] == "status":
                integration.last_webhook_at = utcnow()
                mapped = status_map.get((event.get("status") or "").lower())
                if mapped:
                    errors = event.get("errors") or []
                    error_message = (
                        str(errors[0].get("title") or errors[0].get("message"))
                        if errors
                        else None
                    )
                    message = ConversationService.update_message_status(
                        company_id,
                        event["external_message_id"],
                        mapped,
                        timestamp=self._event_timestamp(event.get("timestamp")),
                        error_message=error_message,
                        commit=False,
                    )
                    processed.append(
                        {"kind": "status", "message_id": message.id if message else None}
                    )
                db.session.commit()
                continue
            if not event.get("external_message_id") or not event.get("from"):
                continue
            existing = QuotaService.enforce_inbound(
                company_id,
                sender=event["from"],
                external_message_id=event["external_message_id"],
            )
            integration.last_webhook_at = utcnow()
            if existing is not None:
                # Meta retries are acknowledged without touching CRM state or
                # dispatching the already-created outbox row again.
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
                external_id=None,
                whatsapp_integration_id=integration.id,
                commit=False,
            )
            message, created = ConversationService.record_inbound(
                company_id,
                conversation_id=conversation.id,
                content=event.get("content") or "",
                external_message_id=event["external_message_id"],
                message_type=event.get("message_type") or "TEXT",
                payload=event.get("payload") or {},
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

    def _credential(self, integration: WhatsAppIntegration, kind: str) -> str | None:
        if self.credential_resolver:
            resolved = self.credential_resolver(integration, kind)
            if resolved:
                return resolved
        if kind == "access_token":
            if integration.access_token_encrypted:
                try:
                    return decrypt_secret(integration.access_token_encrypted)
                except RuntimeError as exc:
                    raise ExternalServiceError(
                        "WhatsApp credentials could not be decrypted", retryable=False
                    ) from exc
            return self.access_token
        if kind == "app_secret":
            if integration.app_secret_encrypted:
                try:
                    return decrypt_secret(integration.app_secret_encrypted)
                except RuntimeError as exc:
                    raise ExternalServiceError(
                        "WhatsApp credentials could not be decrypted", retryable=False
                    ) from exc
            return self.app_secret
        return None

    @staticmethod
    def set_credentials(
        integration: WhatsAppIntegration,
        *,
        access_token: str | None = None,
        app_secret: str | None = None,
        commit: bool = True,
    ) -> WhatsAppIntegration:
        """Encrypt new tenant credentials; blank inputs preserve existing values."""

        if access_token:
            integration.access_token_encrypted = encrypt_secret(access_token.strip())
        if app_secret:
            integration.app_secret_encrypted = encrypt_secret(app_secret.strip())
        if commit:
            db.session.commit()
        return integration

    def _graph_post(
        self, integration: WhatsAppIntegration, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        token = self._credential(integration, "access_token")
        if not token:
            raise ExternalServiceError("WhatsApp access token is not configured")
        request = urllib.request.Request(
            f"https://graph.facebook.com/{self.api_version}/{path.lstrip('/')}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "AutoFlow/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096).decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
                message = data.get("error", {}).get("message", "WhatsApp request failed")
            except json.JSONDecodeError:
                message = "WhatsApp request failed"
            raise ExternalServiceError(
                message,
                retryable=exc.code == 429 or exc.code >= 500,
                status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ExternalServiceError(
                "WhatsApp is temporarily unavailable", retryable=True
            ) from exc

    def _graph_get(
        self,
        integration: WhatsAppIntegration,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        token = self._credential(integration, "access_token")
        if not token:
            raise ExternalServiceError("WhatsApp access token is not configured")
        query = urllib.parse.urlencode(params or {})
        url = f"https://graph.facebook.com/{self.api_version}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "AutoFlow/1.0",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096).decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
                message = data.get("error", {}).get("message", "WhatsApp request failed")
            except json.JSONDecodeError:
                message = "WhatsApp request failed"
            raise ExternalServiceError(
                message,
                retryable=exc.code == 429 or exc.code >= 500,
                status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ExternalServiceError(
                "WhatsApp is temporarily unavailable", retryable=True
            ) from exc

    def check_connection(
        self, company_id: int, integration_id: int | None = None
    ) -> dict[str, Any]:
        query = WhatsAppIntegration.for_company(company_id)
        if integration_id:
            query = query.filter(WhatsAppIntegration.id == integration_id)
        integration = query.one_or_none()
        if integration is None:
            raise ValidationError("WhatsApp integration is not configured")
        try:
            result = self._graph_get(
                integration,
                integration.phone_number_id,
                {
                    "fields": (
                        "display_phone_number,verified_name,quality_rating,"
                        "code_verification_status"
                    )
                },
            )
            integration.display_phone_number = (
                result.get("display_phone_number") or integration.display_phone_number
            )
            metadata = dict(integration.metadata_json or {})
            for key in ("verified_name", "quality_rating", "code_verification_status"):
                if key in result:
                    metadata[key] = result[key]
            integration.metadata_json = metadata
            integration.status = "CONNECTED"
            integration.is_active = True
            integration.last_error = None
            db.session.commit()
            return {
                "connected": True,
                "integration_id": integration.id,
                "display_phone_number": integration.display_phone_number,
                "verified_name": metadata.get("verified_name"),
                "quality_rating": metadata.get("quality_rating"),
            }
        except ExternalServiceError as exc:
            db.session.rollback()
            integration = WhatsAppIntegration.query.filter_by(
                id=integration.id, company_id=int(company_id)
            ).one()
            integration.status = "ERROR"
            integration.last_error = exc.message[:2000]
            db.session.commit()
            raise

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
            raise ValidationError("WhatsApp integration is not connected")
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text[:4096]},
        }
        if reply_to_external_id:
            payload["context"] = {"message_id": reply_to_external_id}
        return self._graph_post(integration, f"{integration.phone_number_id}/messages", payload)

    def mark_read(
        self,
        company_id: int,
        *,
        external_message_id: str,
        integration_id: int | None = None,
    ) -> dict[str, Any]:
        query = WhatsAppIntegration.for_company(company_id).filter_by(
            is_active=True, status="CONNECTED"
        )
        if integration_id:
            query = query.filter(WhatsAppIntegration.id == integration_id)
        integration = query.one_or_none()
        if integration is None:
            raise ValidationError("WhatsApp integration is not connected")
        return self._graph_post(
            integration,
            f"{integration.phone_number_id}/messages",
            {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": external_message_id,
            },
        )
