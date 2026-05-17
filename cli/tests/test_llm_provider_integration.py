from __future__ import annotations

import json
from urllib import request

import pytest

from modelable.llm.config import resolve_llm_config
from modelable.llm.engine import update_definition
from modelable.llm.providers import LLMRequest, LLMResponse, OllamaProvider, build_provider


def test_resolve_llm_config_uses_provider_env():
    config = resolve_llm_config(
        env={
            "MODELABLE_LLM_PROVIDER": "ollama",
            "MODELABLE_LLM_MODEL": "llama3.1",
            "MODELABLE_LLM_BASE_URL": "http://localhost:11434",
        }
    )
    assert config.provider == "ollama"
    assert config.model == "llama3.1"
    assert config.base_url == "http://localhost:11434"
    assert config.source == "environment"


def test_build_provider_requires_model_for_ollama():
    with pytest.raises(ValueError, match="requires a model"):
        build_provider("ollama", model=None, base_url=None)


def test_ollama_provider_posts_chat_payload(monkeypatch):
    captured: dict[str, object] = {}

    class DummyResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req: request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["body"] = req.data.decode("utf-8") if req.data else ""
        captured["timeout"] = timeout
        return DummyResponse(
            json.dumps(
                {
                    "message": {"content": "{\"target\":\"customer.Customer@1\",\"target_kind\":\"model\",\"changes\":[]}"}
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.1", timeout=5.0)
    response = provider.complete(LLMRequest(system="system", user="user", response_format="json"))
    assert response.provider == "ollama"
    assert response.model == "llama3.1"
    assert response.content.startswith("{")
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert "\"model\": \"llama3.1\"" in captured["body"]
    assert captured["timeout"] == 5.0


def test_update_definition_uses_injected_provider(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
"""
    mdl.write_text(original, encoding="utf-8")

    class FakeProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            payload = {
                "target": "customer.Customer@1",
                "target_kind": "model",
                "warnings": ["review classification on email"],
                "changes": [
                    {"kind": "make_optional", "field": "email"},
                    {"kind": "add_field", "field": "loyaltyTier", "type": "string"},
                ],
            }
            return LLMResponse(content=json.dumps(payload), provider="ollama", model="llama3.1")

    result = update_definition(
        tmp_path,
        "customer.Customer@1",
        "make email optional and add loyaltyTier",
        provider=FakeProvider(),
        write=False,
    )
    assert "email?: string" in result.content
    assert "loyaltyTier: string" in result.content
    assert "review classification on email" in result.warnings
    assert mdl.read_text(encoding="utf-8") == original
