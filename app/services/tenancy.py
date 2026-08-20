"""Central tenant authorization helpers.

Routes should derive the company from the authenticated user and then pass it to
services. AI tools and Celery tasks receive it from trusted database context only.
"""

from __future__ import annotations

from flask_login import current_user

from app.models import Company, CompanyMember
from app.services.exceptions import AuthorizationError, NotFoundError, TenantViolationError


ROLE_RANK = {"AGENT": 10, "ADMIN": 20, "OWNER": 30}


def company_id_for_user(user=None) -> int:
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        raise AuthorizationError("Authentication is required")
    company_id = getattr(user, "company_id", None)
    if company_id is None:
        raise AuthorizationError("No active company is selected")
    membership = CompanyMember.query.filter_by(
        company_id=int(company_id), user_id=user.id, status="ACTIVE"
    ).one_or_none()
    if membership is None:
        raise TenantViolationError("User does not belong to the active company")
    company = Company.query.filter_by(id=int(company_id)).one_or_none()
    if company is None or not company.is_active:
        raise AuthorizationError("Company is not active")
    return int(company_id)


def require_role(*roles: str, user=None, company_id: int | None = None) -> CompanyMember:
    user = user or current_user
    tenant_id = int(company_id or company_id_for_user(user))
    membership = CompanyMember.query.filter_by(
        company_id=tenant_id, user_id=user.id, status="ACTIVE"
    ).one_or_none()
    normalized = {role.upper() for role in roles}
    if membership is None or membership.role not in normalized:
        raise AuthorizationError("Insufficient permissions")
    return membership


def tenant_get(model, company_id: int, object_id: int, *, lock: bool = False):
    if company_id is None:
        raise TenantViolationError("company_id is required")
    query = model.query.filter(model.company_id == int(company_id), model.id == object_id)
    if lock:
        query = query.with_for_update()
    instance = query.one_or_none()
    if instance is None:
        # Do not reveal whether an ID exists in another tenant.
        raise NotFoundError(f"{model.__name__} not found")
    return instance


def ensure_same_company(company_id: int, *instances) -> None:
    tenant_id = int(company_id)
    for instance in instances:
        if instance is not None and getattr(instance, "company_id", None) != tenant_id:
            raise TenantViolationError("Cross-company relationship is not allowed")
