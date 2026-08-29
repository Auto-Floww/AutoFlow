"""Cadastro, sessao e recuperacao de senha."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import timedelta
from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db, limiter
from app.models import Company, CompanyMember, User
from app.models.base import utcnow
from app.controllers.http import coerce_bool, failure, payload, success, wants_json
from app.security import encrypt_secret
from app.services.outbox import (
    DispatchOutboxBestEffortService,
    EnqueueOutboxTaskService,
)
from app.validation import RegisterInput


bp = Blueprint("auth", __name__)


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "empresa"
    candidate = slug[:108]
    counter = 2
    while Company.query.filter_by(slug=candidate).first():
        candidate = f"{slug[:104]}-{counter}"
        counter += 1
    return candidate


def _safe_next(target: str | None) -> bool:
    if not target:
        return False
    base = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    return candidate.scheme in {"http", "https"} and base.netloc == candidate.netloc


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "GET":
        return render_template("auth/register.html")

    raw = payload()
    raw.pop("confirm_password", None)
    raw.pop("terms", None)
    try:
        form = RegisterInput.model_validate(raw)
    except Exception as exc:  # Pydantic apresenta os detalhes sem ecoar a senha.
        errors = exc.errors(include_url=False) if hasattr(exc, "errors") else None
        return failure(
            "Revise os dados do cadastro.", errors=errors, endpoint="auth.register"
        )

    email = str(form.email).lower()
    if User.query.filter(db.func.lower(User.email) == email).first():
        return failure("Este e-mail ja possui uma conta.", endpoint="auth.login", status=409)

    try:
        company = Company(name=form.company_name, slug=_slugify(form.company_name))
        db.session.add(company)
        db.session.flush()

        user = User(
            name=form.name,
            email=email,
            active_company_id=company.id,
        )
        user.set_password(form.password)
        db.session.add(user)
        db.session.flush()
        db.session.add(
            CompanyMember(
                company_id=company.id,
                user_id=user.id,
                role="OWNER",
                status="ACTIVE",
                joined_at=utcnow(),
            )
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return failure("Nao foi possivel criar a conta com estes dados.", status=409)

    login_user(user, remember=True)
    return success(
        "Conta criada. Bem-vindo ao AutoFlow!",
        data={"redirect": url_for("dashboard.index")},
        endpoint="dashboard.index",
        status=201,
    )


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "GET":
        return render_template("auth/login.html", next=request.args.get("next", ""))

    data = payload()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user or not user.is_active or not user.check_password(password):
        return failure("E-mail ou senha invalidos.", endpoint="auth.login", status=401)
    if not user.company_id or not user.membership_for(user.company_id):
        return failure("Sua conta nao possui uma empresa ativa.", status=403)

    user.last_login_at = utcnow()
    db.session.commit()
    login_user(user, remember=coerce_bool(data.get("remember"), False))

    next_url = data.get("next") or request.args.get("next")
    destination = next_url if _safe_next(next_url) else url_for("dashboard.index")
    if wants_json():
        return success("Login realizado.", data={"redirect": destination})
    flash("Que bom ter voce de volta.", "success")
    return redirect(destination)


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return success("Sessao encerrada.", endpoint="auth.login")


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("3 per 15 minutes", methods=["POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("auth/forgot_password.html")

    email = str(payload().get("email", "")).strip().lower()
    user = User.query.filter(db.func.lower(User.email) == email).first()
    task_payload = {}
    company_id = None
    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        token_digest = hashlib.sha256(token.encode()).hexdigest()
        user.reset_token_hash = token_digest
        user.reset_token_expires_at = utcnow() + timedelta(minutes=30)
        company_id = user.company_id
        task_payload = {
            "user_id": user.id,
            "reset_token_encrypted": encrypt_secret(token),
        }
        idempotency_key = f"password-reset-email:{user.id}:{token_digest}"
    else:
        # Persist a real no-op task so unknown and known addresses follow the same
        # durable/async path and have equivalent external behavior.
        idempotency_key = f"password-reset-email:noop:{secrets.token_hex(16)}"

    outbox = EnqueueOutboxTaskService().execute(
        "password_reset_email",
        task_payload,
        idempotency_key=idempotency_key,
        company_id=company_id,
    )
    db.session.commit()
    DispatchOutboxBestEffortService().execute(outbox.id)

    response_data = {"delivery": "email"}
    return success(
        "Se o e-mail estiver cadastrado, enviaremos as instrucoes.",
        data=response_data,
        endpoint="auth.login",
    )


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes", methods=["POST"])
def reset_password(token: str):
    digest = hashlib.sha256(token.encode()).hexdigest()
    user = User.query.filter_by(reset_token_hash=digest).first()
    valid = bool(
        user
        and user.reset_token_expires_at
        and user.reset_token_expires_at >= utcnow()
        and hmac.compare_digest(user.reset_token_hash, digest)
    )
    if not valid:
        return failure("Este link expirou ou ja foi usado.", endpoint="auth.forgot_password", status=400)
    if request.method == "GET":
        return render_template("auth/reset_password.html", token=token)

    data = payload()
    password = str(data.get("password", ""))
    if len(password) < 8 or password != str(data.get("confirm_password", password)):
        return failure("Use ao menos 8 caracteres e confirme a mesma senha.", status=400)
    user.set_password(password)
    user.reset_token_hash = None
    user.reset_token_expires_at = None
    db.session.commit()
    return success("Senha alterada. Entre novamente.", endpoint="auth.login")


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per 15 minutes", methods=["POST"])
def change_password():
    if request.method == "GET":
        return render_template("auth/change_password.html")
    data = payload()
    current_password = str(data.get("current_password", ""))
    new_password = str(data.get("password", data.get("new_password", "")))
    confirmation = str(data.get("confirm_password", new_password))
    if not current_user.check_password(current_password):
        return failure("A senha atual esta incorreta.", status=400)
    if len(new_password) < 8 or new_password != confirmation:
        return failure("A nova senha precisa ter 8 caracteres e confirmacao igual.")
    current_user.set_password(new_password)
    db.session.commit()
    logout_user()
    return success("Senha atualizada. Entre novamente.", endpoint="auth.login")


class AuthController:
    """HTTP controller for account registration and authentication."""

    register = staticmethod(register)
    login = staticmethod(login)
    logout = staticmethod(logout)
    forgot_password = staticmethod(forgot_password)
    reset_password = staticmethod(reset_password)
    change_password = staticmethod(change_password)


bp.view_functions.update(
    {
        "register": AuthController.register,
        "login": AuthController.login,
        "logout": AuthController.logout,
        "forgot_password": AuthController.forgot_password,
        "reset_password": AuthController.reset_password,
        "change_password": AuthController.change_password,
    }
)
