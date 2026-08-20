"""Typed service-layer errors safe for routes and background jobs."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code = "domain_error"
    status_code = 400

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(DomainError):
    code = "validation_error"
    status_code = 422


class NotFoundError(DomainError):
    code = "not_found"
    status_code = 404


class ConflictError(DomainError):
    code = "conflict"
    status_code = 409


class RateLimitError(DomainError):
    """A safe, typed signal for application-level cost/backpressure limits."""

    code = "rate_limit_exceeded"
    status_code = 429

    def __init__(
        self,
        message: str = "Inbound message quota exceeded",
        *,
        retry_after: int = 60,
        scope: str | None = None,
        limit: int | None = None,
    ):
        self.retry_after = max(1, int(retry_after))
        details: dict[str, Any] = {"retry_after": self.retry_after}
        if scope:
            details["scope"] = scope
        if limit is not None:
            details["limit"] = int(limit)
        super().__init__(message, details=details)


class AuthorizationError(DomainError):
    code = "forbidden"
    status_code = 403


class TenantViolationError(AuthorizationError):
    code = "tenant_violation"


class ExternalServiceError(DomainError):
    code = "external_service_error"
    status_code = 502

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, details=details)
        self.retryable = retryable
        self.external_status = status
