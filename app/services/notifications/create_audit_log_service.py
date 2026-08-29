"""Use case for appending an audit-log record."""

import app.services.notification_service as legacy


class CreateAuditLogService:
    def execute(
        self,
        company_id: int,
        *,
        action: str,
        entity_type: str,
        entity_id: str | int | None = None,
        actor_user_id: int | None = None,
        changes: dict | None = None,
        context: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        commit: bool = True,
    ):
        return legacy.NotificationService.audit(
            company_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            changes=changes,
            context=context,
            ip_address=ip_address,
            user_agent=user_agent,
            commit=commit,
        )


__all__ = ["CreateAuditLogService"]
