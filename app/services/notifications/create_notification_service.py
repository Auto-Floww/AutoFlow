"""Use case for creating tenant notifications."""

import app.services.notification_service as legacy


class CreateNotificationService:
    def execute(
        self,
        company_id: int,
        *,
        notification_type: str,
        title: str,
        body: str | None = None,
        user_id: int | None = None,
        link_url: str | None = None,
        data: dict | None = None,
        idempotency_key: str | None = None,
        commit: bool = True,
    ):
        return legacy.NotificationService.create(
            company_id,
            notification_type=notification_type,
            title=title,
            body=body,
            user_id=user_id,
            link_url=link_url,
            data=data,
            idempotency_key=idempotency_key,
            commit=commit,
        )


__all__ = ["CreateNotificationService"]
