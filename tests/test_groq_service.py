"""Integração Groq isolada por mocks, sem chamadas de rede."""

import json

import pytest
from freezegun import freeze_time

from app.extensions import db
from app.models import Company, Conversation
from app.services.catalog_service import CatalogService
from app.services.customer_service import CustomerOperations
from app.services.groq_service import GroqService
from app.services.tool_registry import ToolContext


@freeze_time("2026-11-07 01:30:00")
def test_booking_prompt_uses_company_date_and_resolves_internal_ids():
    company = Company(name="Salão", timezone="America/Sao_Paulo")

    prompt = GroqService.build_system_prompt(company, settings=None)

    assert "sexta-feira, 2026-11-06" in prompt
    assert "Nunca peça ao cliente IDs internos" in prompt
    assert "search_appointment_services" in prompt
    assert "get_available_appointments sem professional_id" in prompt


@pytest.mark.parametrize(
    ("profile_name", "expected_name"),
    [("Rafael Vieira Gonzaga", '"Rafael"'), ("Ana-Lúcia Silva", '"Ana-Lúcia"'), (None, "null")],
)
def test_answer_uses_first_name_from_whatsapp_contact(
    company_factory, monkeypatch, profile_name, expected_name
):
    company = company_factory()
    phone = "+55 11 99999-1234"
    customer = CustomerOperations.upsert_from_whatsapp(
        company.id, phone=phone, name=profile_name
    )
    conversation = Conversation(company_id=company.id, customer_id=customer.id)
    db.session.add(conversation)
    db.session.flush()
    gateway = GroqService(api_key="groq-test-secret")

    def reply(messages, **kwargs):
        prompt = messages[0]["content"]
        assert f"Primeiro nome do contato (dado de perfil): {expected_name}\n" in prompt
        assert phone not in prompt
        if profile_name:
            assert profile_name not in prompt
        return "Resposta", {}

    monkeypatch.setattr(gateway, "run_tool_loop", reply)
    assert gateway.answer_conversation(conversation, history=[]) == ("Resposta", {})


def test_tool_call_loop_executes_allowlisted_tool_then_returns_answer(monkeypatch):
    service = GroqService(api_key="groq-test-secret")
    responses = iter(
        [
            {
                "model": "modelo-teste",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_products",
                                        "arguments": json.dumps({"query": "camiseta"}),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"total_tokens": 15},
            },
            {
                "model": "modelo-teste",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Não encontrei esse produto no catálogo.",
                        }
                    }
                ],
                "usage": {"total_tokens": 9},
            },
        ]
    )
    captured_messages = []

    def fake_chat(messages, **kwargs):
        captured_messages.append(list(messages))
        return next(responses)

    monkeypatch.setattr(service, "chat_completion", fake_chat)
    monkeypatch.setattr(CatalogService, "search", staticmethod(lambda *args, **kwargs: []))

    answer, metadata = service.run_tool_loop(
        [{"role": "user", "content": "Vocês têm camiseta?"}],
        context=ToolContext(company_id=7),
    )

    assert answer == "Não encontrei esse produto no catálogo."
    assert metadata["tools"] == [{"name": "search_products", "ok": True}]
    tool_result = captured_messages[1][-1]
    assert tool_result["role"] == "tool"
    assert json.loads(tool_result["content"]) == {"ok": True, "data": []}


def test_chat_completion_builds_groq_request_without_exposing_key(monkeypatch):
    service = GroqService(
        api_key="groq-super-secret",
        model="llama-test",
        base_url="https://api.groq.com/openai/v1",
    )
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @staticmethod
        def read():
            return json.dumps(
                {
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = service.chat_completion([{"role": "user", "content": "Oi"}])

    assert response["choices"][0]["message"]["content"] == "ok"
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["authorization"] == "Bearer groq-super-secret"
    assert "groq-super-secret" not in json.dumps(captured["body"])
