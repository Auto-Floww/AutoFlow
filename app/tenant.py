"""Helpers de autorizacao e isolamento por empresa."""

from functools import wraps

from flask import abort, g
from flask_login import current_user


ROLE_LEVEL = {"AGENT": 10, "ADMIN": 20, "OWNER": 30}


def current_company_id() -> int:
    """Retorna a empresa da sessao; nunca aceita company_id vindo do cliente."""

    company_id = getattr(current_user, "company_id", None)
    membership = (
        current_user.membership_for(company_id)
        if company_id is not None and hasattr(current_user, "membership_for")
        else None
    )
    if company_id is None or membership is None:
        abort(403, description="Usuario sem empresa ativa.")
    return int(company_id)


def tenant_query(model):
    if not hasattr(model, "company_id"):
        raise TypeError(f"{model.__name__} nao e uma entidade multi-tenant")
    return model.query.filter(model.company_id == current_company_id())


def tenant_get_or_404(model, object_id):
    return tenant_query(model).filter(model.id == object_id).first_or_404()


def roles_required(*roles):
    minimum = min((ROLE_LEVEL.get(role, 999) for role in roles), default=999)

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            role = str(getattr(current_user, "role", "")).upper()
            if ROLE_LEVEL.get(role, 0) < minimum:
                abort(403)
            g.active_company_id = current_company_id()
            return view(*args, **kwargs)

        return wrapped

    return decorator
