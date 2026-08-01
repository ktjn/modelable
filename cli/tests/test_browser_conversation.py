from __future__ import annotations

import json
from pathlib import Path

import pytest

from modelable.browser.api import BrowserCompiler
from modelable.browser.conversation import BrowserConversationBackend, BrowserConversationService, _logical_path
from modelable.browser.dto import BrowserSource
from modelable.browser.rag import BrowserRetrievalError
from modelable.llm.conversation_plan import AddField, ChangeSetPlan, FieldSpec
from modelable.llm.conversation_planner import PendingPlanRequest
from modelable.parser.ir import PrimitiveType
from modelable.rag.retriever import RetrievedChunk

CUSTOMER_URI = "inmemory:///customer.mdl"
BILLING_URI = "inmemory:///billing.mdl"
CUSTOMER_SOURCE = """\
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
"""
BILLING_SOURCE = """\
domain billing {
  owner: "billing-team"
}
"""


def valid_projection_plan() -> dict[str, object]:
    return {
        "kind": "change_set",
        "summary": "Create billing.CustomerProjection@1",
        "operations": [
            {
                "kind": "create_projection",
                "domain": "billing",
                "name": "CustomerProjection",
                "source": {
                    "model": "customer.Customer",
                    "version": 1,
                    "alias": "customer",
                },
                "fields": [
                    {
                        "name": "customerId",
                        "mapping": {
                            "kind": "direct",
                            "source_alias": "customer",
                            "source_field": "customerId",
                        },
                    }
                ],
            }
        ],
    }


def test_browser_conversation_previews_and_applies_projection() -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(
        1,
        (
            BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),
            BrowserSource(uri=BILLING_URI, text=BILLING_SOURCE, version=1),
        ),
    )
    service = BrowserConversationService(compiler, id_factory=lambda: "request-1")

    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Suggest a projection for billing",
        active_document_uri=CUSTOMER_URI,
        line=3,
        character=10,
    )
    assert isinstance(pending, PendingPlanRequest)
    preview = service.resume(
        session_id="session-1",
        request_id=pending.request_id,
        workspace_revision=1,
        content=json.dumps(valid_projection_plan()),
    )
    applied = service.apply(
        session_id="session-1",
        action_id=preview.reply.change_set_id or "",
        workspace_revision=1,
    )

    assert preview.reply.kind == "preview"
    assert "projection" in preview.reply.preview_files[0].after_text
    assert applied.workspace_revision == 2
    assert "projection CustomerProjection" in compiler.sources[1].text


def test_browser_conversation_preserves_nested_workspace_paths() -> None:
    assert _logical_path("file:///domains/customer.mdl") == Path("domains/customer.mdl")
    assert _logical_path("file:///consumers/customer.mdl") == Path("consumers/customer.mdl")


def test_browser_conversation_rejects_unsafe_workspace_paths() -> None:
    with pytest.raises(ValueError, match="safe relative document path"):
        _logical_path("file:///domains/../customer.mdl")


def test_browser_conversation_previews_and_promotes_compilation() -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(
        1,
        (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),),
    )
    service = BrowserConversationService(compiler, id_factory=lambda: "request-1")

    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Compile this workspace to JSON Schema",
    )
    assert isinstance(pending, PendingPlanRequest)
    preview = service.resume(
        session_id="session-1",
        request_id=pending.request_id,
        workspace_revision=1,
        content=json.dumps(
            {
                "kind": "compile",
                "target": "json-schema",
                "domains": [],
                "output": None,
                "descriptor_set": False,
                "summary": "Compile to JSON Schema",
            }
        ),
    )
    applied = service.apply(
        session_id="session-1",
        action_id=preview.reply.change_set_id or "",
        workspace_revision=1,
    )

    assert preview.reply.kind == "preview"
    assert preview.reply.compilation_files
    assert preview.reply.compilation_files[0].after_text is not None
    assert applied.reply.kind == "applied"
    assert applied.reply.compilation_files == preview.reply.compilation_files


def test_browser_docs_turn_retrieves_and_resumes_with_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(1, (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),))

    class FakeRetriever:
        def __init__(self, index_url: str, asset_root: str) -> None:
            assert index_url.endswith("docs-index/manifest.json")
            assert asset_root.endswith("playground/")

        def search(self, query: str, *, limit: int = 8) -> list[RetrievedChunk]:
            assert query == "How do I install it?"
            return [
                RetrievedChunk(
                    id=1,
                    external_id="guide.md#install",
                    url="https://example.test/guide/#install",
                    score=1.0,
                    title="Guide",
                    heading="Install",
                    content="Run the installer.",
                    source_path="guide.md",
                    heading_path=["Guide", "Install"],
                    content_hash="hash",
                )
            ]

    monkeypatch.setattr("modelable.browser.conversation.BrowserDocumentationRetriever", FakeRetriever)
    service = BrowserConversationService(compiler, id_factory=lambda: "docs-request")
    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="/docs How do I install it?",
        documentation_index_url="https://example.test/playground/docs-index/manifest.json",
        documentation_asset_root="https://example.test/playground/",
    )
    assert isinstance(pending, PendingPlanRequest)
    assert "Documentation evidence" in pending.request.user

    answer = service.resume(
        session_id="session-1",
        request_id=pending.request_id,
        workspace_revision=1,
        content="Use the installer.",
    )
    assert answer.reply.kind == "answer"
    assert "guide.md#install" in answer.reply.text


def test_browser_automatic_documentation_retrieval_is_lazy_and_returns_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(1, (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),))
    constructed: list[tuple[str, str]] = []

    class FakeRetriever:
        def __init__(self, index_url: str, asset_root: str) -> None:
            constructed.append((index_url, asset_root))

        def search(self, query: str, *, limit: int = 8) -> list[RetrievedChunk]:
            assert query == "How do I configure the compiler?"
            assert limit == 8
            return [
                RetrievedChunk(
                    id=1,
                    external_id="guide.md#configuration",
                    url="https://example.test/guide/#configuration",
                    score=0.9,
                    title="Guide",
                    heading="Configuration",
                    content="Set compiler options in modelable.toml.",
                    source_path="guide.md",
                    heading_path=["Guide", "Configuration"],
                    content_hash="hash",
                )
            ]

    monkeypatch.setattr("modelable.browser.conversation.BrowserDocumentationRetriever", FakeRetriever)
    service = BrowserConversationService(compiler, id_factory=lambda: "docs-request")

    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="How do I configure the compiler?",
        documentation_index_url="https://example.test/playground/docs-index/manifest.json",
        documentation_asset_root="https://example.test/playground/",
    )

    assert isinstance(pending, PendingPlanRequest)
    assert pending.request.response_format == "text"
    assert constructed == [
        (
            "https://example.test/playground/docs-index/manifest.json",
            "https://example.test/playground/",
        )
    ]

    answer = service.resume(
        session_id="session-1",
        request_id=pending.request_id,
        workspace_revision=1,
        content="Use `modelable.toml` [S1].",
    )

    assert answer.reply.retrieval_used is True
    assert answer.reply.route_reason == "automatic_documentation_signal"
    assert answer.reply.citations[0].external_id == "guide.md#configuration"


def test_browser_mutation_intent_does_not_load_documentation_retriever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(1, (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),))

    class UnexpectedRetriever:
        def __init__(self, _index_url: str, _asset_root: str) -> None:
            raise AssertionError("mutation intent must not load the documentation index")

    monkeypatch.setattr("modelable.browser.conversation.BrowserDocumentationRetriever", UnexpectedRetriever)
    service = BrowserConversationService(compiler, id_factory=lambda: "planner-request")

    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Compile the workspace using the documented JSON Schema option",
        documentation_index_url="https://example.test/playground/docs-index/manifest.json",
        documentation_asset_root="https://example.test/playground/",
    )

    assert isinstance(pending, PendingPlanRequest)
    assert pending.request.response_format == "json"


def test_browser_automatic_documentation_opt_out_uses_planner_but_explicit_docs_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(1, (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),))
    searches: list[str] = []

    class FakeRetriever:
        def __init__(self, _index_url: str, _asset_root: str) -> None:
            pass

        def search(self, query: str, *, limit: int = 8) -> list[RetrievedChunk]:
            del limit
            searches.append(query)
            return [
                RetrievedChunk(
                    id=1,
                    external_id="guide.md#configuration",
                    url="https://example.test/guide/#configuration",
                    score=0.9,
                    title="Guide",
                    heading="Configuration",
                    content="Configure the compiler.",
                    source_path="guide.md",
                    heading_path=["Guide", "Configuration"],
                    content_hash="hash",
                )
            ]

    monkeypatch.setattr("modelable.browser.conversation.BrowserDocumentationRetriever", FakeRetriever)
    service = BrowserConversationService(compiler, id_factory=lambda: "request")
    documentation = {
        "documentation_index_url": "https://example.test/playground/docs-index/manifest.json",
        "documentation_asset_root": "https://example.test/playground/",
        "automatic_documentation": False,
    }

    automatic = service.turn(
        session_id="automatic-disabled",
        workspace_revision=1,
        message="How do I configure the compiler?",
        **documentation,
    )
    explicit = service.turn(
        session_id="explicit-override",
        workspace_revision=1,
        message="/docs How do I configure the compiler?",
        **documentation,
    )

    assert isinstance(automatic, PendingPlanRequest)
    assert automatic.request.response_format == "json"
    assert isinstance(explicit, PendingPlanRequest)
    assert explicit.request.response_format == "text"
    assert searches == ["How do I configure the compiler?"]


@pytest.mark.parametrize("configure_index", [False, True])
def test_browser_automatic_documentation_missing_index_or_retrieval_failure_falls_back_to_planner(
    monkeypatch: pytest.MonkeyPatch,
    configure_index: bool,
) -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(1, (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),))

    class FailingRetriever:
        def __init__(self, _index_url: str, _asset_root: str) -> None:
            pass

        def search(self, _query: str, *, limit: int = 8) -> list[RetrievedChunk]:
            del limit
            raise BrowserRetrievalError("index unavailable")

    monkeypatch.setattr("modelable.browser.conversation.BrowserDocumentationRetriever", FailingRetriever)
    service = BrowserConversationService(compiler, id_factory=lambda: "planner-request")
    documentation = (
        {
            "documentation_index_url": "https://example.test/playground/docs-index/manifest.json",
            "documentation_asset_root": "https://example.test/playground/",
        }
        if configure_index
        else {}
    )

    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="How do I configure the compiler?",
        **documentation,
    )

    assert isinstance(pending, PendingPlanRequest)
    assert pending.request.response_format == "json"


def test_browser_automatic_documentation_provider_failure_falls_back_to_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(1, (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),))

    class FakeRetriever:
        def __init__(self, _index_url: str, _asset_root: str) -> None:
            pass

        def search(self, _query: str, *, limit: int = 8) -> list[RetrievedChunk]:
            del limit
            return [
                RetrievedChunk(
                    id=1,
                    external_id="guide.md#configuration",
                    url="https://example.test/guide/#configuration",
                    score=0.9,
                    title="Guide",
                    heading="Configuration",
                    content="Configure the compiler.",
                    source_path="guide.md",
                    heading_path=["Guide", "Configuration"],
                    content_hash="hash",
                )
            ]

    request_ids = iter(("docs-request", "planner-request"))
    monkeypatch.setattr("modelable.browser.conversation.BrowserDocumentationRetriever", FakeRetriever)
    service = BrowserConversationService(compiler, id_factory=lambda: next(request_ids))
    documentation = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="How do I configure the compiler?",
        documentation_index_url="https://example.test/playground/docs-index/manifest.json",
        documentation_asset_root="https://example.test/playground/",
    )
    assert isinstance(documentation, PendingPlanRequest)

    fallback = service.fail(
        session_id="session-1",
        request_id=documentation.request_id,
        workspace_revision=1,
        error="provider unavailable",
    )

    assert isinstance(fallback, PendingPlanRequest)
    assert fallback.request_id == "planner-request"
    assert fallback.request.response_format == "json"


def test_browser_conversation_invalidates_preview_after_external_workspace_change() -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(
        1,
        (
            BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),
            BrowserSource(uri=BILLING_URI, text=BILLING_SOURCE, version=1),
        ),
    )
    service = BrowserConversationService(compiler, id_factory=lambda: "request-1")
    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Suggest a projection for billing",
        active_document_uri=CUSTOMER_URI,
        line=3,
        character=10,
    )
    assert isinstance(pending, PendingPlanRequest)
    preview = service.resume(
        session_id="session-1",
        request_id=pending.request_id,
        workspace_revision=1,
        content=json.dumps(valid_projection_plan()),
    )
    externally_changed = BILLING_SOURCE.replace("billing-team", "new-team")
    compiler.open_workspace(
        2,
        (
            BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),
            BrowserSource(uri=BILLING_URI, text=externally_changed, version=2),
        ),
    )

    applied = service.apply(
        session_id="session-1",
        action_id=preview.reply.change_set_id or "",
        workspace_revision=2,
    )

    assert applied.reply.kind == "error"
    assert compiler.sources[1].text == externally_changed


def test_browser_conversation_rejects_compile_options_it_cannot_honor() -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(
        1,
        (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),),
    )
    service = BrowserConversationService(compiler, id_factory=lambda: "request-1")
    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Compile only customer to JSON Schema",
    )
    assert isinstance(pending, PendingPlanRequest)

    result = service.resume(
        session_id="session-1",
        request_id=pending.request_id,
        workspace_revision=1,
        content=json.dumps(
            {
                "kind": "compile",
                "target": "json-schema",
                "domains": ["customer"],
                "output": None,
                "descriptor_set": False,
                "summary": "Compile customer to JSON Schema",
            }
        ),
    )

    assert result.reply.kind == "error"
    assert "does not support domain filters" in result.reply.text


def test_browser_conversation_provider_failure_preserves_prior_preview() -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(
        1,
        (
            BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),
            BrowserSource(uri=BILLING_URI, text=BILLING_SOURCE, version=1),
        ),
    )
    request_ids = iter(("request-1", "request-2"))
    service = BrowserConversationService(compiler, id_factory=lambda: next(request_ids))
    initial = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Suggest a projection for billing",
        active_document_uri=CUSTOMER_URI,
        line=3,
        character=10,
    )
    assert isinstance(initial, PendingPlanRequest)
    preview = service.resume(
        session_id="session-1",
        request_id=initial.request_id,
        workspace_revision=1,
        content=json.dumps(valid_projection_plan()),
    )
    refinement = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Add another field to the projection",
    )
    assert isinstance(refinement, PendingPlanRequest)

    failed = service.fail(
        session_id="session-1",
        request_id=refinement.request_id,
        workspace_revision=1,
        error="provider unavailable",
    )
    applied = service.apply(
        session_id="session-1",
        action_id=preview.reply.change_set_id or "",
        workspace_revision=1,
    )

    assert failed.reply.kind == "unsupported"
    assert applied.reply.kind == "applied"


def test_browser_conversation_backend_preview_accepts_session_editable_refs() -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(
        1,
        (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),),
    )
    backend = BrowserConversationBackend(compiler)
    plan = ChangeSetPlan(
        summary="Add email",
        operations=[
            AddField(
                target="customer.Customer@1",
                field=FieldSpec(name="email", type=PrimitiveType(kind="string"), optional=True),
            )
        ],
    )

    reply = backend.preview_source_change(
        plan,
        None,
        session_editable_refs=frozenset({"customer.Customer@1"}),
    )

    assert reply.kind == "preview"
