"""Criptografia de credenciais armazenadas por tenant."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from flask import current_app


def _cipher() -> MultiFernet:
    configured = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    keys = [value.strip().encode() for value in configured.split(",") if value.strip()]
    if not keys:
        # Conveniente apenas em desenvolvimento. Producao deve fornecer uma chave
        # Fernet separada e estavel para permitir rotacao de SECRET_KEY.
        derived = hashlib.sha256(current_app.config["SECRET_KEY"].encode()).digest()
        keys = [base64.urlsafe_b64encode(derived)]
        if not current_app.testing:
            current_app.logger.warning(
                "CREDENTIAL_ENCRYPTION_KEY ausente; usando chave derivada no ambiente atual."
            )
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError) as exc:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY invalida") from exc


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Nao foi possivel descriptografar a credencial") from exc
