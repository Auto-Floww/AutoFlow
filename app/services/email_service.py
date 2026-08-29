"""Envio transacional de e-mails sem acoplar o app a um provedor específico."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

from app.services.exceptions import ExternalServiceError


class EmailGateway:
    """Adaptador SMTP pequeno para mensagens transacionais do AutoFlow."""

    @staticmethod
    def is_configured() -> bool:
        return bool(
            current_app.config.get("SMTP_HOST")
            and current_app.config.get("MAIL_FROM")
        )

    @classmethod
    def send_password_reset(
        cls, recipient: str | None, reset_url: str | None
    ) -> dict[str, str]:
        # Unknown accounts deliberately execute the same asynchronous task path,
        # but terminate here without contacting SMTP.
        if not recipient or not reset_url:
            return {"status": "noop"}
        if not cls.is_configured():
            raise ExternalServiceError(
                "Email delivery is not configured", retryable=True
            )

        message = EmailMessage()
        message["Subject"] = "Redefina sua senha do AutoFlow"
        message["From"] = current_app.config["MAIL_FROM"]
        message["To"] = recipient
        message.set_content(
            "Recebemos uma solicitação para redefinir sua senha do AutoFlow.\n\n"
            f"Use este link nas próximas 30 minutos:\n{reset_url}\n\n"
            "Se você não fez esta solicitação, ignore esta mensagem."
        )

        host = current_app.config["SMTP_HOST"]
        port = int(current_app.config["SMTP_PORT"])
        timeout = float(current_app.config["SMTP_TIMEOUT"])
        use_ssl = bool(current_app.config["SMTP_USE_SSL"])
        context = ssl.create_default_context()

        try:
            if use_ssl:
                connection = smtplib.SMTP_SSL(
                    host, port, timeout=timeout, context=context
                )
            else:
                connection = smtplib.SMTP(host, port, timeout=timeout)

            with connection as smtp:
                if current_app.config["SMTP_USE_TLS"] and not use_ssl:
                    smtp.starttls(context=context)
                username = current_app.config.get("SMTP_USERNAME")
                if username:
                    smtp.login(username, current_app.config.get("SMTP_PASSWORD", ""))
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise ExternalServiceError(
                "Email delivery is temporarily unavailable", retryable=True
            ) from exc
        return {"status": "sent"}


# Backwards-compatible alias; sending reset mail is an ``auth`` use case.
EmailService = EmailGateway
