"""Integração Groq isolada por mocks, sem chamadas de rede."""

import json

from app.services.catalog_service import CatalogService
from app.services.groq_service import GroqService
from app.services.tool_registry import ToolContext


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
