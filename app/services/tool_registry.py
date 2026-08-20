"""Allow-listed, Pydantic-validated tool execution for Groq function calling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.services.exceptions import DomainError, ValidationError


PROTECTED_ARGUMENTS = {
    "company_id",
    "tenant_id",
    "actor_user_id",
    "access_token",
    "api_key",
}


class ToolInput(BaseModel):
    class Config:
        extra = "forbid"
        str_strip_whitespace = True


@dataclass(frozen=True)
class ToolContext:
    company_id: int
    conversation_id: int | None = None
    customer_id: int | None = None
    actor_user_id: int | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments_model: type[BaseModel]
    handler: Callable[..., Any]

    def groq_schema(self) -> dict[str, Any]:
        if hasattr(self.arguments_model, "model_json_schema"):
            parameters = self.arguments_model.model_json_schema()
        else:  # Pydantic 1.x
            parameters = self.arguments_model.schema()
        parameters.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "id"):
        return {"id": value.id}
    return str(value)


class ToolRegistry:
    def __init__(self, *, max_argument_bytes: int = 12_000, max_result_bytes: int = 24_000):
        self._tools: dict[str, ToolSpec] = {}
        self.max_argument_bytes = max_argument_bytes
        self.max_result_bytes = max_result_bytes

    def register(self, spec: ToolSpec) -> None:
        if not spec.name.replace("_", "").isalnum():
            raise ValueError("Tool names may contain only letters, numbers, and underscores")
        if spec.name in self._tools:
            raise ValueError(f"Tool {spec.name!r} is already registered")
        self._tools[spec.name] = spec

    def schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        selected = names or list(self._tools)
        return [self._tools[name].groq_schema() for name in selected if name in self._tools]

    def execute(
        self,
        name: str,
        raw_arguments: str | dict[str, Any] | None,
        context: ToolContext,
    ) -> dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            raise ValidationError("Unknown or disabled tool")
        if isinstance(raw_arguments, str):
            if len(raw_arguments.encode("utf-8")) > self.max_argument_bytes:
                raise ValidationError("Tool arguments are too large")
            try:
                arguments = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError as exc:
                raise ValidationError("Tool arguments are not valid JSON") from exc
        else:
            arguments = raw_arguments or {}
        if not isinstance(arguments, dict):
            raise ValidationError("Tool arguments must be an object")
        forbidden = PROTECTED_ARGUMENTS.intersection(arguments)
        if forbidden:
            raise ValidationError("Protected context cannot be supplied by the model")
        try:
            if hasattr(spec.arguments_model, "model_validate"):
                validated = spec.arguments_model.model_validate(arguments)
                values = validated.model_dump(exclude_none=True)
            else:
                validated = spec.arguments_model.parse_obj(arguments)
                values = validated.dict(exclude_none=True)
        except PydanticValidationError as exc:
            errors = [
                {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                for item in exc.errors()[:10]
            ]
            raise ValidationError("Invalid tool arguments", details={"fields": errors}) from exc
        result = spec.handler(context=context, **values)
        payload = {"ok": True, "data": result}
        encoded = json.dumps(payload, ensure_ascii=False, default=_json_default)
        if len(encoded.encode("utf-8")) > self.max_result_bytes:
            payload = {
                "ok": False,
                "error": "result_too_large",
                "message": "The result was too large; narrow the search.",
            }
        return payload

    @staticmethod
    def safe_error(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, DomainError):
            return {"ok": False, **exc.to_dict()}
        return {
            "ok": False,
            "error": "tool_execution_failed",
            "message": "The requested operation could not be completed.",
        }
