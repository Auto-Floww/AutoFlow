"""Notification persistence and audit helpers."""

from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AuditLog, CompanyMember, Notification
from app.services.tenancy import ensure_same_company


class NotificationService:
    @staticmethod
    def create(
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
    ) -> list[Notification]:
        if user_id:
            members = CompanyMember.query.filter_by(
                company_id=int(company_id), user_id=user_id, status="ACTIVE"
            ).all()
        else:
            members = CompanyMember.query.filter_by(
                company_id=int(company_id), status="ACTIVE"
            ).all()
        targets = [member.user_id for member in members]
        if user_id and not targets:
            return []
        if not targets:
            # A company-wide notification remains visible even before staff is added.
            targets = [None]
        notifications: list[Notification] = []
        keys: list[str] = []
        for target in targets:
            derived_key = None
            if idempotency_key:
                raw_key = f"{idempotency_key}:{target if target is not None else 'all'}"
                derived_key = (
                    raw_key
                    if len(raw_key) <= 190
                    else "sha256:" + hashlib.sha256(raw_key.encode()).hexdigest()
                )
                existing = Notification.query.filter_by(
                    company_id=int(company_id), idempotency_key=derived_key
                ).one_or_none()
                if existing:
                    notifications.append(existing)
                    continue
                keys.append(derived_key)
            notifications.append(
                Notification(
                    company_id=int(company_id),
                    user_id=target,
                    notification_type=notification_type[:48],
                    title=title[:180],
                    body=body,
                    link_url=link_url,
                    data_json=data or {},
                    idempotency_key=derived_key,
                )
            )
        db.session.add_all(notifications)
        try:
            db.session.flush()
            if commit:
                db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if keys:
                return Notification.for_company(company_id).filter(
                    Notification.idempotency_key.in_(keys)
                ).all()
            raise
        return notifications

    @staticmethod
    def audit(
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
    ) -> AuditLog:
        log = AuditLog(
            company_id=int(company_id),
            action=action[:100],
            entity_type=entity_type[:80],
            entity_id=str(entity_id)[:100] if entity_id is not None else None,
            actor_user_id=actor_user_id,
            changes_json=changes or {},
            context_json=context or {},
            ip_address=ip_address,
            user_agent=(user_agent or "")[:500] or None,
        )
        db.session.add(log)
        if commit:
            db.session.commit()
        return log
