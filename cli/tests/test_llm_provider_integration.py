from __future__ import annotations

import json
from pathlib import Path
from urllib import request

import pytest
from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.llm.chat import ChatState, chat_reply, chat_turn
from modelable.llm.config import LlmConfig, resolve_llm_config
from modelable.llm.engine import update_definition
from modelable.llm.providers import LLMRequest, LLMResponse, OllamaProvider, build_provider
from modelable.operations.compilation import CompilationService


class SequenceProvider:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content=self.responses.pop(0),
            provider="fake",
            model="test-model",
        )


def _create_customer_plan_json() -> str:
    return json.dumps(
        {
            "kind": "change_set",
            "summary": "Create customer.Customer@1",
            "assumptions": ["Address is inline"],
            "operations": [
                {
                    "kind": "create_model",
                    "domain": "customer",
                    "name": "Customer",
                    "model_kind": "entity",
                    "fields": [
                        {
                            "name": "customerId",
                            "type": {"kind": "uuid"},
                            "annotations": [{"kind": "key"}],
                        },
                        {
                            "name": "address",
                            "type": {
                                "kind": "object",
                                "fields": [
                                    {"name": "street", "type": {"kind": "string"}},
                                    {"name": "city", "type": {"kind": "string"}},
                                    {"name": "postalCode", "type": {"kind": "string"}},
                                    {"name": "country", "type": {"kind": "string"}},
                                ],
                            },
                        },
                    ],
                }
            ],
        }
    )


def _provenance_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.provenance.json")


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


def test_build_provider_requires_api_key_for_anthropic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider("anthropic", model="claude-sonnet-4-20250514", base_url=None)


def test_anthropic_provider_posts_messages_payload(monkeypatch):
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
        captured["headers"] = dict(req.headers)
        captured["timeout"] = timeout
        return DummyResponse(
            json.dumps(
                {
                    "content": [{"type": "text", "text": "captured"}],
                    "usage": {"input_tokens": 12, "output_tokens": 4},
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    provider = build_provider("anthropic", model="claude-sonnet-4-20250514", base_url="https://api.anthropic.com")
    assert provider is not None
    response = provider.complete(LLMRequest(system="system", user="user", response_format="json"))
    assert response.provider == "anthropic"
    assert response.model == "claude-sonnet-4-20250514"
    assert response.content == "captured"
    assert response.prompt_tokens == 12
    assert response.completion_tokens == 4
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert '"model": "claude-sonnet-4-20250514"' in captured["body"]
    assert '"system": "system"' in captured["body"]
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert captured["timeout"] == 120.0


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
                {"message": {"content": '{"target":"customer.Customer@1","target_kind":"model","changes":[]}'}}
            ).encode("utf-8")
        )

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.1", timeout=5.0)
    response = provider.complete(LLMRequest(system="system", user="user", response_format="json"))
    assert response.provider == "ollama"
    assert response.model == "llama3.1"
    assert response.content.startswith("{")
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert '"model": "llama3.1"' in captured["body"]
    assert captured["timeout"] == 5.0


def test_update_definition_uses_injected_provider(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
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
    assert not _provenance_path(mdl).exists()


def test_update_definition_repairs_invalid_provider_output(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
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
    assert result.provider == "ollama"
    assert result.model == "llama3.1"
    assert result.diagnostics_repaired == 1
    assert mdl.read_text(encoding="utf-8") == original
    assert not _provenance_path(mdl).exists()


def test_update_definition_can_disable_repair_attempts(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
"""
    mdl.write_text(original, encoding="utf-8")

    calls: list[LLMRequest] = []

    class BrokenProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            calls.append(request)
            return LLMResponse(content="{not valid json", provider="ollama", model="llama3.1")

    with pytest.raises(ValueError, match="invalid update plan"):
        update_definition(
            tmp_path,
            "customer.Customer@1",
            "make email optional",
            provider=BrokenProvider(),
            llm_config=LlmConfig(
                provider="ollama", model="llama3.1", base_url=None, repair_attempts=0, source="workspace"
            ),
            write=False,
        )

    assert len(calls) == 1
    assert mdl.read_text(encoding="utf-8") == original
    assert not _provenance_path(mdl).exists()


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
  owner: "test-team"
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
            json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "kind": "clarification",
                                "question": "Should I stage email as optional?",
                                "reason": "The request asks how rather than requesting a change.",
                            }
                        )
                    }
                }
            ).encode("utf-8")
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
    assert "Should I stage email as optional?" in result.output
    assert "Return JSON only matching the supplied closed schema" in captured["system"]
    assert "Never emit raw patches" in captured["system"]


def test_chat_command_uses_anthropic_provider_when_available(tmp_path, monkeypatch):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
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
        captured["system"] = json.loads(req.data.decode("utf-8"))["system"]
        captured["url"] = req.full_url
        return DummyResponse(
            json.dumps(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "kind": "clarification",
                                    "question": "Should I stage email as optional?",
                                    "reason": "The request asks how rather than requesting a change.",
                                }
                            ),
                        }
                    ],
                    "usage": {"input_tokens": 11, "output_tokens": 3},
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

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
            "anthropic",
            "--model",
            "claude-sonnet-4-20250514",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Should I stage email as optional?" in result.output
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert "Return JSON only matching the supplied closed schema" in captured["system"]
    assert "Never emit raw patches" in captured["system"]


def test_chat_single_message_previews_complete_entity_without_writing(tmp_path, monkeypatch):
    source = tmp_path / "customer.mdl"
    original = 'domain customer {\n  owner: "customer-team"\n}\n'
    source.write_text(original, encoding="utf-8")
    provider = SequenceProvider(_create_customer_plan_json())
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: provider)

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--message",
            "add a customer entity with address",
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Apply change set" in result.output
    assert "customer.Customer@1" in result.output
    assert source.read_text(encoding="utf-8") == original


def test_chat_interactive_session_applies_its_pending_change(tmp_path, monkeypatch):
    source = tmp_path / "customer.mdl"
    source.write_text(
        'domain customer {\n  owner: "customer-team"\n}\n',
        encoding="utf-8",
    )
    provider = SequenceProvider(_create_customer_plan_json())
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: provider)

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
        ],
        input="add a customer entity with address\n/apply\n/exit\n",
    )

    assert result.exit_code == 0, result.output
    assert "Apply change set" in result.output
    assert "Applied change set" in result.output
    assert "entity Customer @ 1" in source.read_text(encoding="utf-8")
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    ("arguments", "input_text"),
    [
        (["--message", "/compile rust"], None),
        ([], "/compile rust\n/quit\n"),
        ([], "/compile rust\n"),
    ],
)
def test_chat_closes_compile_staging_on_single_message_quit_and_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    input_text: str | None,
) -> None:
    (tmp_path / "workspace.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""",
        encoding="utf-8",
    )
    service = CompilationService(temp_root=tmp_path.parent, new_id=lambda: "compile-cli")
    pending = []
    original_preview = service.preview

    def recording_preview(*args, **kwargs):
        result = original_preview(*args, **kwargs)
        pending.append(result)
        return result

    from modelable.llm.conversation import ConversationSession

    def session_factory(**kwargs):
        return ConversationSession(**kwargs, compilation_service=service)

    monkeypatch.setattr(service, "preview", recording_preview)
    monkeypatch.setattr("modelable.commands.llm.ConversationSession", session_factory)

    result = CliRunner().invoke(
        cli,
        ["chat", "--path", str(tmp_path), *arguments],
        input=input_text,
    )

    assert result.exit_code == 0, result.output
    assert "Only the literal /apply" in result.output
    assert pending
    assert not pending[0].staging_dir.exists()


def test_chat_closes_compile_staging_when_turn_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "workspace.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""",
        encoding="utf-8",
    )
    service = CompilationService(temp_root=tmp_path.parent, new_id=lambda: "compile-error")
    pending = []
    original_preview = service.preview

    def recording_preview(*args, **kwargs):
        result = original_preview(*args, **kwargs)
        pending.append(result)
        return result

    from modelable.llm.conversation import ConversationSession

    class FailingSession(ConversationSession):
        def turn(self, message: str):
            if message == "explode":
                raise RuntimeError("injected chat failure")
            return super().turn(message)

    def session_factory(**kwargs):
        return FailingSession(**kwargs, compilation_service=service)

    monkeypatch.setattr(service, "preview", recording_preview)
    monkeypatch.setattr("modelable.commands.llm.ConversationSession", session_factory)

    result = CliRunner().invoke(
        cli,
        ["chat", "--path", str(tmp_path)],
        input="/compile rust\nexplode\n",
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert pending
    assert not pending[0].staging_dir.exists()


def test_chat_honors_zero_configured_plan_repair_attempts(tmp_path, monkeypatch):
    source = tmp_path / "customer.mdl"
    original = 'domain customer {\n  owner: "customer-team"\n}\n'
    source.write_text(original, encoding="utf-8")
    provider = SequenceProvider("{not valid json", _create_customer_plan_json())
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: provider)
    monkeypatch.setenv("MODELABLE_LLM_REPAIR_ATTEMPTS", "0")

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--message",
            "add a customer entity with address",
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "did not return a valid typed plan" in result.output
    assert len(provider.requests) == 1
    assert source.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("/describe customer.Customer@1", "customerId"),
        ("/context", "projection CustomerView @ 1"),
        ("Who owns customer.Customer@1?", "customer-team"),
        ("Show lineage for customer.CustomerView@1", "customer.Customer@1.customerId"),
        ("What depends on customer.Customer@1?", "customer.CustomerView@1"),
    ],
)
def test_chat_offline_queries_remain_available(tmp_path, message, expected):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--message",
            message,
        ],
    )

    assert result.exit_code == 0, result.output
    assert expected in result.output


def test_chat_offline_creation_request_requires_provider_without_writing(tmp_path):
    source = tmp_path / "customer.mdl"
    original = 'domain customer {\n  owner: "customer-team"\n}\n'
    source.write_text(original, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--message",
            "add a customer entity with address",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Configure an LLM provider" in result.output
    assert source.read_text(encoding="utf-8") == original


def test_update_command_uses_provider_flags(tmp_path, monkeypatch):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
"""
    mdl.write_text(original, encoding="utf-8")

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
        payload = json.loads(req.data.decode("utf-8"))
        captured["system"] = payload["messages"][0]["content"]
        captured["url"] = req.full_url
        return DummyResponse(
            json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "target": "customer.Customer@1",
                                "target_kind": "model",
                                "warnings": ["provider-backed update"],
                                "changes": [{"kind": "make_optional", "field": "email"}],
                            }
                        )
                    }
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "update",
            "customer.Customer@1",
            "make email optional",
            "--path",
            str(tmp_path),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--base-url",
            "http://localhost:11434",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert "provider-backed update" in result.output
    assert "email?: string" in mdl.read_text(encoding="utf-8")
    assert (tmp_path / "workspace.mdl.provenance.json").exists()


def test_update_command_uses_anthropic_provider_flags(tmp_path, monkeypatch):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
"""
    mdl.write_text(original, encoding="utf-8")

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
        payload = json.loads(req.data.decode("utf-8"))
        captured["system"] = payload["messages"][0]["content"]
        captured["url"] = req.full_url
        return DummyResponse(
            json.dumps(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "target": "customer.Customer@1",
                                    "target_kind": "model",
                                    "warnings": ["anthropic update"],
                                    "changes": [{"kind": "make_optional", "field": "email"}],
                                }
                            ),
                        }
                    ],
                    "usage": {"input_tokens": 9, "output_tokens": 2},
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "update",
            "customer.Customer@1",
            "make email optional",
            "--path",
            str(tmp_path),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-4-20250514",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert "anthropic update" in result.output
    assert "email?: string" in mdl.read_text(encoding="utf-8")
    assert (tmp_path / "workspace.mdl.provenance.json").exists()


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
    assert (
        mdl.read_text(encoding="utf-8")
        == """
domain customer {
  owner: "platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }
}
"""
    )


def test_chat_update_command_shows_preview_with_provider(tmp_path):
    from modelable.llm.providers import LLMResponse

    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
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


def test_chat_freeform_edit_request_requires_provider_without_writing(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
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
    assert "Configure an LLM provider" in response
    assert mdl.read_text(encoding="utf-8") == original


def test_chat_question_about_edit_does_not_auto_write(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    original = """
domain customer {
  owner: "test-team"
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
