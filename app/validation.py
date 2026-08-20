"""Validacao Pydantic compartilhada pelos endpoints JSON e formularios."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from flask import request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterInput(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    company_name: str = Field(min_length=2, max_length=160)


class LoginInput(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False


class CustomerInput(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=8, max_length=32)
    email: EmailStr | None = None
    organization: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    status: str = Field(default="NEW", max_length=30)


class ProductInput(StrictModel):
    name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=6000)
    sku: str = Field(min_length=1, max_length=80)
    category: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    price: Decimal = Field(ge=0)
    promotional_price: Decimal | None = Field(default=None, ge=0)
    image_url: str | None = Field(default=None, max_length=500)
    active: bool = True


class InventoryMovementInput(StrictModel):
    inventory_id: int = Field(gt=0)
    movement_type: str
    quantity: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=255)

    @field_validator("movement_type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        value = value.upper()
        if value not in {"IN", "OUT", "ADJUSTMENT"}:
            raise ValueError("Tipo de movimentacao invalido")
        return value


class AppointmentInput(StrictModel):
    customer_id: int = Field(gt=0)
    service_id: int = Field(gt=0)
    professional_id: int | None = Field(default=None, gt=0)
    starts_at: datetime
    notes: str | None = Field(default=None, max_length=2000)


class MessageInput(StrictModel):
    body: str = Field(min_length=1, max_length=4096)


def request_data() -> dict[str, Any]:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


def parse_input(schema: type[StrictModel]):
    try:
        return schema.model_validate(request_data()), None
    except ValidationError as exc:
        return None, exc.errors(include_url=False)
