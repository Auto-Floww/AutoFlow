"""Fixtures integradas com a application factory e SQLite em memória."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMember, User


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch):
    """Cria uma aplicação completamente isolada, sem serviços externos."""

    monkeypatch.setenv("TEST_DATABASE_URL", "sqlite:///:memory:")
    flask_app = create_app("testing")
    flask_app.config.update(
        SERVER_NAME="localhost",
        WTF_CSRF_ENABLED=False,
        RATELIMIT_ENABLED=False,
        CELERY={"task_always_eager": True, "task_eager_propagates": True},
    )

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()
        # Python 3.14 alerta sobre conexões SQLite finalizadas pelo GC. Fechar o
        # pool explicitamente mantém a suíte limpa mesmo com warnings como erro.
        db.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


@pytest.fixture()
def company_factory(app) -> Iterator[Callable[..., Company]]:
    created = 0

    def factory(**overrides) -> Company:
        nonlocal created
        created += 1
        unique = uuid4().hex[:8]
        company = Company(
            name=overrides.pop("name", f"Empresa {created}"),
            slug=overrides.pop("slug", f"empresa-{unique}"),
            **overrides,
        )
        db.session.add(company)
        db.session.flush()
        return company

    yield factory


@pytest.fixture()
def user_factory(app, company_factory) -> Iterator[Callable[..., User]]:
    created = 0

    def factory(
        *,
        company: Company | None = None,
        password: str = "SenhaSegura123!",
        role: str = "OWNER",
        commit: bool = True,
        **overrides,
    ) -> User:
        nonlocal created
        created += 1
        company = company or company_factory()
        unique = uuid4().hex[:8]
        user = User(
            name=overrides.pop("name", f"Usuário {created}"),
            email=overrides.pop("email", f"user-{unique}@example.com"),
            active_company_id=company.id,
            **overrides,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        db.session.add(
            CompanyMember(
                company_id=company.id,
                user_id=user.id,
                role=role,
                status="ACTIVE",
            )
        )
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return user

    yield factory


@pytest.fixture()
def tenant_user(user_factory) -> User:
    return user_factory(
        name="Ana Proprietária",
        email="ana@example.com",
        password="SenhaSegura123!",
    )


@pytest.fixture()
def login_as(client):
    """Autentica um usuário sem acoplar testes de domínio ao formulário."""

    def login(user: User):
        with client.session_transaction() as session:
            session["_user_id"] = user.get_id()
            session["_fresh"] = True
        return client

    return login
