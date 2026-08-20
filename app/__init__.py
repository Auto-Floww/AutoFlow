"""Application factory do AutoFlow."""

import hmac
import logging
import os
from logging.config import dictConfig
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import CONFIGS
from app.extensions import cors, csrf, db, limiter, login_manager, make_celery, migrate


def _configure_logging(level: str) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"level": level, "handlers": ["console"]},
        }
    )


def create_app(config_name: str | None = None) -> Flask:
    config_name = config_name or os.getenv("FLASK_ENV", "development")
    if config_name not in CONFIGS:
        raise RuntimeError(
            f"Ambiente desconhecido: {config_name!r}. Use development, testing ou production."
        )
    config_class = CONFIGS[config_name]

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    _validate_runtime_config(app, config_name)
    proxy_hops = int(app.config.get("TRUST_PROXY_HOPS", 0) or 0)
    if proxy_hops:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_hops,
            x_proto=proxy_hops,
            x_host=proxy_hops,
        )
    _configure_logging(app.config["LOG_LEVEL"])

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=True,
    )
    make_celery(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Entre na sua conta para continuar."
    login_manager.login_message_category = "warning"

    @login_manager.unauthorized_handler
    def unauthorized():
        if _wants_json():
            return jsonify(error="authentication_required", message="Autenticacao necessaria."), 401
        return redirect(url_for("auth.login", next=request.full_path))

    # Garante que todos os metadados estejam registrados antes das migracoes.
    from app import models  # noqa: F401,WPS433

    @login_manager.user_loader
    def load_user(user_id: str):
        from app.models import User

        try:
            raw_id, separator, session_version = str(user_id).partition(".")
            if not separator or not session_version:
                return None
            user = db.session.get(User, int(raw_id))
        except (TypeError, ValueError):
            return None
        if user is None or not user.is_active or user.company_id is None:
            return None
        if not hmac.compare_digest(user.get_id(), str(user_id)):
            return None
        return user

    _register_blueprints(app)
    _register_handlers(app)
    _register_context(app)
    _register_cli(app)
    return app


def _validate_runtime_config(app: Flask, config_name: str) -> None:
    if config_name != "production":
        return
    problems = []
    secret_key = str(app.config.get("SECRET_KEY") or "")
    if secret_key == "change-me-before-production" or len(secret_key) < 32:
        problems.append("SECRET_KEY")
    if not os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip():
        problems.append("CREDENTIAL_ENCRYPTION_KEY")
    database_url = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    parsed_database = urlparse(database_url)
    if (
        not database_url.startswith("mysql+pymysql://")
        or not parsed_database.username
        or not parsed_database.password
    ):
        problems.append("DATABASE_URL (mysql+pymysql)")
    redis_url = urlparse(str(app.config.get("REDIS_URL", "")))
    if redis_url.scheme not in {"redis", "rediss"} or not redis_url.password:
        problems.append("REDIS_URL (autenticado)")
    rate_limit_url = urlparse(str(app.config.get("RATELIMIT_STORAGE_URI", "")))
    if rate_limit_url.scheme not in {"redis", "rediss"} or not rate_limit_url.password:
        problems.append("RATELIMIT_STORAGE_URI (Redis autenticado)")
    if not str(app.config.get("APP_URL", "")).startswith("https://"):
        problems.append("APP_URL (https)")
    if not app.config.get("SMTP_HOST") or not app.config.get("MAIL_FROM"):
        problems.append("SMTP_HOST/MAIL_FROM")
    if problems:
        raise RuntimeError(
            "Configuracao de producao incompleta: " + ", ".join(problems)
        )
    configured_hosts = [
        item.strip()
        for item in os.getenv("TRUSTED_HOSTS", "").split(",")
        if item.strip()
    ]
    app_host = urlparse(str(app.config["APP_URL"])).hostname
    app.config["TRUSTED_HOSTS"] = configured_hosts or ([app_host] if app_host else [])


def _register_blueprints(app: Flask) -> None:
    from app.routes.appointments import bp as appointments_bp
    from app.routes.auth import bp as auth_bp
    from app.routes.conversations import bp as conversations_bp
    from app.routes.customers import bp as customers_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.delivery import bp as delivery_bp
    from app.routes.faq import bp as faq_bp
    from app.routes.inventory import bp as inventory_bp
    from app.routes.products import bp as products_bp
    from app.routes.settings import bp as settings_bp
    from app.routes.whatsapp import bp as whatsapp_bp

    for blueprint in (
        auth_bp,
        dashboard_bp,
        conversations_bp,
        customers_bp,
        products_bp,
        inventory_bp,
        delivery_bp,
        appointments_bp,
        faq_bp,
        settings_bp,
        whatsapp_bp,
    ):
        app.register_blueprint(blueprint)


def _wants_json() -> bool:
    return request.path.startswith("/api/") or (
        request.accept_mimetypes.best == "application/json"
        and request.accept_mimetypes["application/json"]
        >= request.accept_mimetypes["text/html"]
    )


def _register_handlers(app: Flask) -> None:
    from app.services.exceptions import DomainError

    @app.errorhandler(DomainError)
    def handle_domain_error(error):
        if _wants_json():
            return jsonify(error.to_dict()), error.status_code
        return render_template(
            "errors/400.html", message=error.message
        ), error.status_code

    @app.get("/")
    def root():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    @app.get("/health")
    @limiter.exempt
    def health():
        return jsonify(status="ok", service="autoflow")

    @app.errorhandler(CSRFError)
    def handle_csrf(error):
        if _wants_json():
            return jsonify(error="csrf_invalid", message=error.description), 400
        return render_template("errors/400.html", message=error.description), 400

    @app.errorhandler(400)
    def bad_request(error):
        message = getattr(error, "description", "Requisicao invalida.")
        if _wants_json():
            return jsonify(error="bad_request", message=message), 400
        return render_template("errors/400.html", message=message), 400

    @app.errorhandler(403)
    def forbidden(error):
        if _wants_json():
            return jsonify(error="forbidden", message="Acesso nao autorizado."), 403
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        if _wants_json():
            return jsonify(error="not_found", message="Recurso nao encontrado."), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def rate_limited(error):
        if _wants_json():
            return jsonify(error="rate_limited", message="Muitas tentativas. Aguarde."), 429
        return render_template("errors/429.html"), 429

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.exception("Erro interno nao tratado", exc_info=error)
        if _wants_json():
            return jsonify(error="internal_error", message="Nao foi possivel concluir."), 500
        return render_template("errors/500.html"), 500

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if not app.debug:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: https:; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "script-src 'self' https://cdn.jsdelivr.net; connect-src 'self'; "
                "object-src 'none'; base-uri 'self'; form-action 'self'; "
                "frame-ancestors 'self'",
            )
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if (
            response.mimetype in {"text/html", "application/json"}
            and (
                current_user.is_authenticated
                or request.path.startswith("/reset-password/")
            )
        ):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


def _register_context(app: Flask) -> None:
    @app.context_processor
    def global_template_context():
        context = {
            "app_name": "AutoFlow",
            "app_url": app.config["APP_URL"],
            "landing_page_url": app.config["LANDING_PAGE_URL"],
            "whatsapp_connected": False,
            "notification_count": 0,
            "unread_conversations": 0,
            "plan_usage": 0,
            "plan_usage_label": "Nenhuma conversa registrada",
        }
        if current_user.is_authenticated and getattr(current_user, "company_id", None):
            from app.models import Conversation, Notification, WhatsAppIntegration

            company_id = current_user.company_id
            total_conversations = Conversation.for_company(company_id).count()
            unread = Conversation.for_company(company_id).filter(
                Conversation.unread_count > 0
            ).count()
            unread_notifications = Notification.for_company(company_id).filter(
                Notification.is_read.is_(False),
                db.or_(Notification.user_id.is_(None), Notification.user_id == current_user.id),
            ).count()
            company = current_user.company
            conversation_limit = int((company.settings_json or {}).get("conversation_limit", 0) or 0)
            context.update(
                whatsapp_connected=WhatsAppIntegration.for_company(company_id).filter_by(
                    status="CONNECTED", is_active=True
                ).first()
                is not None,
                notification_count=unread_notifications,
                unread_conversations=unread,
                plan_name=company.plan.title() if company else "Starter",
                plan_usage=(
                    min(100, round(total_conversations * 100 / conversation_limit))
                    if conversation_limit
                    else 0
                ),
                plan_usage_label=(
                    f"{total_conversations} de {conversation_limit} conversas"
                    if conversation_limit
                    else f"{total_conversations} conversa{'s' if total_conversations != 1 else ''} registrada{'s' if total_conversations != 1 else ''}"
                ),
            )
        return context


def _register_cli(app: Flask) -> None:
    @app.cli.command("check-config")
    def check_config():
        """Verifica a presenca das configuracoes criticas sem revelar secrets."""

        required = {
            "SECRET_KEY": app.config.get("SECRET_KEY"),
            "DATABASE_URL": app.config.get("SQLALCHEMY_DATABASE_URI"),
            "GROQ_API_KEY": app.config.get("GROQ_API_KEY"),
            "WHATSAPP_ACCESS_TOKEN": app.config.get("WHATSAPP_ACCESS_TOKEN"),
            "WHATSAPP_VERIFY_TOKEN": app.config.get("WHATSAPP_VERIFY_TOKEN"),
        }
        for key, value in required.items():
            logging.getLogger(__name__).info("%s: %s", key, "ok" if value else "ausente")
