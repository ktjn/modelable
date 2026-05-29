from __future__ import annotations

import json
from urllib import request

import pytest
from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.llm.chat import ChatState, chat_reply, chat_turn
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


def test_update_definition_repairs_invalid_provider_output(tmp_path):
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

    calls: list[LLMRequest] = []

    class RepairingProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            calls.append(request)
            if len(calls) == 1:
                return LLMResponse(content="{not valid json", provider="ollama", model="llama3.1")
            payload = {
                "target": "customer.Customer@1",
                "target_kind": "model",
                "warnings": ["repaired output"],
                "changes": [
                    {"kind": "make_optional", "field": "email"},
                ],
            }
            return LLMResponse(content=json.dumps(payload), provider="ollama", model="llama3.1")

    result = update_definition(
        tmp_path,
        "customer.Customer@1",
        "make email optional",
        provider=RepairingProvider(),
        write=False,
    )

    assert len(calls) == 2
    assert "email?: string" in result.content
    assert "repaired output" in result.warnings
    assert mdl.read_text(encoding="utf-8") == original


def test_chat_reply_falls_back_to_local_qa(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    response = chat_reply(workspace, "Who owns customer.Customer@1?")
    assert "platform" in response


def test_chat_command_uses_provider_when_available(tmp_path, monkeypatch):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
""",
        encoding="utf-8",
    )

    class DummyResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    captured: dict[str, str] = {}

    def fake_urlopen(req: request.Request, timeout: float):
        captured["system"] = json.loads(req.data.decode("utf-8"))["messages"][0]["content"]
        return DummyResponse(
            json.dumps({"message": {"content": "I can apply that change directly in chat."}}).encode("utf-8")
        )

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--message",
            "How do I make email optional?",
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--base-url",
            "http://localhost:11434",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "apply that change directly" in result.output
    assert "previewed through the update pipeline" in captured["system"]
    assert "modelable update" not in captured["system"]


def test_chat_slash_commands_cover_help_describe_recommend_and_update(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    state = ChatState()

    help_text = chat_turn(workspace, "/help", path=tmp_path, state=state)
    assert "/update <ref> <instruction>" in help_text

    focus_text = chat_turn(workspace, "/ref customer.Customer@1", path=tmp_path, state=state)
    assert "Focused on customer.Customer@1" in focus_text

    describe_text = chat_turn(workspace, "/describe", path=tmp_path, state=state)
    assert "customer.Customer@1" in describe_text

    recommend_text = chat_turn(workspace, "/recommend customer.Customer@1 billing", path=tmp_path, state=state)
    assert "billing" in recommend_text

    update_text = chat_turn(
        workspace,
        "/update customer.Customer@1 make email optional",
        path=tmp_path,
        state=state,
    )
    assert "Wrote changes to" not in update_text
    assert "@@" in update_text
    assert "email?: string" in update_text
    assert mdl.read_text(encoding="utf-8") == """
domain customer {
  owner: "platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
"""


def test_chat_update_command_shows_preview_with_provider(tmp_path):
    from modelable.llm.providers import LLMRequest, LLMResponse

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
    workspace = load_workspace(tmp_path)
    state = ChatState()

    class FakeProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            payload = {
                "target": "customer.Customer@1",
                "target_kind": "model",
                "warnings": ["confirm classification before publishing"],
                "changes": [
                    {"kind": "make_optional", "field": "email"},
                ],
            }
            return LLMResponse(content=json.dumps(payload), provider="ollama", model="llama3.1")

    response = chat_turn(
        workspace,
        "/update customer.Customer@1 make email optional",
        path=tmp_path,
        state=state,
        provider=FakeProvider(),
    )
    assert "Wrote changes to" not in response
    assert "email?: string" in response
    assert "email?: string" not in mdl.read_text(encoding="utf-8")
    assert "confirm classification before publishing" in response


def test_chat_freeform_edit_request_shows_preview_without_writing(tmp_path):
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
    workspace = load_workspace(tmp_path)
    state = ChatState(ref="customer.Customer@1")

    response = chat_turn(
        workspace,
        "Please make email optional",
        path=tmp_path,
        state=state,
    )
    assert "Wrote changes to" not in response
    assert "email?: string" in response
    assert mdl.read_text(encoding="utf-8") == original


def test_chat_question_about_edit_does_not_auto_write(tmp_path):
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
    workspace = load_workspace(tmp_path)
    state = ChatState(ref="customer.Customer@1")

    response = chat_turn(
        workspace,
        "How do I make email optional?",
        path=tmp_path,
        state=state,
    )
    assert "Wrote changes to" not in response
    assert mdl.read_text(encoding="utf-8") == original
