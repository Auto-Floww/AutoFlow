"""Per-company AI and WhatsApp settings."""

from __future__ import annotations

from app.extensions import db
from app.models.base import ReprMixin, TenantMixin, TimestampMixin


class AISettings(db.Model, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "ai_settings"

    id = db.Column(db.Integer, primary_key=True)
    assistant_name = db.Column(db.String(100), nullable=False, default="Assistente")
    personality = db.Column(db.Text)
    tone = db.Column(db.String(80), nullable=False, default="natural e objetivo")
    greeting_message = db.Column(db.Text)
    after_hours_message = db.Column(db.Text)
    rules = db.Column(db.Text)
    commercial_instructions = db.Column(db.Text)
    transfer_instructions = db.Column(db.Text)
    model = db.Column(db.String(100))
    temperature = db.Column(db.Float, nullable=False, default=0.2)
    max_tokens = db.Column(db.Integer, nullable=False, default=800)
    history_limit = db.Column(db.Integer, nullable=False, default=30)
    summary_threshold = db.Column(db.Integer, nullable=False, default=60)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    auto_reply_enabled = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.UniqueConstraint("company_id", name="uq_ai_settings_company"),
        db.CheckConstraint(
            "temperature >= 0 AND temperature <= 2", name="ck_ai_settings_temperature"
        ),
        db.CheckConstraint("max_tokens > 0", name="ck_ai_settings_max_tokens"),
        db.CheckConstraint("history_limit > 0", name="ck_ai_settings_history"),
    )


class WhatsAppIntegration(db.Model, TenantMixin, TimestampMixin, ReprMixin):
    __tablename__ = "whatsapp_integrations"

    id = db.Column(db.Integer, primary_key=True)
    display_phone_number = db.Column(db.String(32))
    phone_number_id = db.Column(db.String(100), nullable=False, unique=True, index=True)
    business_account_id = db.Column(db.String(100), index=True)
    # Credentials are intentionally not exposed through any serializer. A deployment
    # should inject them from a secret manager; these columns accept ciphertext only.
    access_token_encrypted = db.Column(db.Text)
    app_secret_encrypted = db.Column(db.Text)
    status = db.Column(db.String(24), nullable=False, default="PENDING", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    last_webhook_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text)
    metadata_json = db.Column("metadata", db.JSON, nullable=False, default=dict)

    __table_args__ = (
        db.UniqueConstraint("company_id", name="uq_whatsapp_company"),
        db.CheckConstraint(
            "status IN ('PENDING','CONNECTED','ERROR','DISCONNECTED')",
            name="ck_whatsapp_status",
        ),
    )
