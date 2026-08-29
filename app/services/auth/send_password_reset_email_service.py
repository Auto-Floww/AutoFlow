"""Use case for delivering a password-reset email."""

import app.services.email_service as legacy


class SendPasswordResetEmailService:
    def execute(self, recipient: str | None, reset_url: str | None) -> dict[str, str]:
        return legacy.EmailService.send_password_reset(recipient, reset_url)


__all__ = ["SendPasswordResetEmailService"]
