from __future__ import annotations

import errno
import json
from pathlib import Path

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.llm.conversation import ConversationReply, ConversationSession
from modelable.llm.conversation_plan import ChangeSetPlan, CompilePlan, CreateModel, FieldSpec
from modelable.llm.providers import LLMRequest, LLMResponse
from modelable.lsp import definition, document_symbols
from modelable.lsp import workspace as lsp_workspace
from modelable.lsp.conversation_protocol import (
    ConversationChangeSetParams,
    ConversationPosition,
    ConversationTurnParams,
)
from modelable.lsp.conversation_service import (
    ConversationSessionError,
    LspConversationService,
)
from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.operations.compilation import CompilationService, PendingCompilation
from modelable.parser.ir import AnnKey, PrimitiveType
from modelable.rag.index import build_documentation_index
from modelable.rag.model import DocumentationChunk
from modelable.rag.retriever import DocumentationRetriever


def test_find_focused_ref_returns_containing_definition(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    index = LspWorkspaceIndex()
    index.upsert_document(source.as_uri(), source.read_text(encoding="utf-8"))

    assert document_symbols.find_focused_ref(index, source.as_uri(), 3, 8) == "customer.Customer@1"
    assert document_symbols.find_focused_ref(index, source.as_uri(), 0, 0) is None


def test_find_focused_ref_covers_multiline_projection_header(tmp_path: Path) -> None:
    source = tmp_path / "features.mdl"
    source.write_text(
        'domain "ml" {\n'
        '  owner: "ml-team"\n'
        "  projection Features @ 1\n"
        "    from customer.Customer @ 1 as customer\n"
        "    join billing.Bill @ 1 as bill on customer.customerId == bill.customerId\n"
        "  {\n"
        "    customerId <- customer.customerId\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    index = LspWorkspaceIndex()
    index.upsert_document(source.as_uri(), source.read_text(encoding="utf-8"))

    assert document_symbols.find_focused_ref(index, source.as_uri(), 4, 10) == "ml.Features@1"


def test_find_workspace_root_uses_nearest_manifest(tmp_path: Path) -> None:
    root = tmp_path / "modelable"
    nested = root / "domains" / "customer"
    nested.mkdir(parents=True)
    (root / "workspace.mdl").write_text('workspace "example" {}\n', encoding="utf-8")
    source = nested / "customer.mdl"
    source.write_text('domain customer { owner: "customer-team" }\n', encoding="utf-8")

    assert lsp_workspace.find_workspace_root(source) == root
    assert lsp_workspace.find_workspace_root(tmp_path / "outside.mdl") is None


def test_definition_location_for_ref_exposes_existing_resolver(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    location = definition.definition_location_for_ref(
        load_workspace(tmp_path),
        "customer.Customer@1",
    )

    assert location is not None
    assert location.uri == source.as_uri()
    assert location.range.start.line == 2


def _write_customer_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    return source


def _make_documentation_index(root: Path) -> Path:
    index = root / "docs-index"
    build_documentation_index(
        [
            DocumentationChunk(
                external_id="guide.md#install",
                source_path="guide.md",
                url="https://example.test/guide/#install",
                language="en",
                title="Guide",
                heading="Install",
                heading_path=["Guide", "Install"],
                content="How do I configure install? Install with uv.",
                chunk_index=0,
            )
        ],
        index,
    )
    return index / "manifest.json"


def _replace_manifest_shard_file(manifest_path: Path, section: str, shard_file: str) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if section in {"terms", "docs"}:
        manifest["shards"][section][0]["file"] = shard_file
    elif section == "facets":
        manifest["shards"]["facets"] = [{"field": "title", "file": shard_file}]
    elif section in {"pins", "synonyms"}:
        manifest[section] = {"en": shard_file}
    elif section == "fuzzy":
        manifest["fuzzy"] = {"en": {"file": shard_file}}
    elif section == "vectors":
        manifest["vectors"] = {
            "dims": 1,
            "quantization": "float32",
            "embeddingProvider": {"type": "test"},
            "shards": {"en": shard_file},
        }
    else:
        raise ValueError(f"unsupported manifest section: {section}")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _session_factory(root: Path, focused_ref: str | None) -> ConversationSession:
    return ConversationSession(
        path=root,
        provider=None,
        focused_ref=focused_ref,
    )


def _turn_params(
    root: Path,
    *,
    session_id: str = "session-1",
    create_session: bool,
    dirty_document_uris: tuple[str, ...] = (),
) -> ConversationTurnParams:
    return ConversationTurnParams.model_validate(
        {
            "protocolVersion": 2,
            "sessionId": session_id,
            "createSession": create_session,
            "workspaceUri": root.as_uri(),
            "message": "is the workspace valid?",
            "dirtyDocumentUris": list(dirty_document_uris),
        }
    )


def test_registry_requires_create_flag_for_unknown_session(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    service = LspConversationService(
        session_factory=_session_factory,
        clock=lambda: 10.0,
    )

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, create_session=False))

    reply = service.turn(_turn_params(root, create_session=True))

    assert reply["kind"] == "answer"
    assert reply["sessionId"] == "session-1"


def test_first_turn_includes_no_provider_notice_when_unconfigured(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    service = LspConversationService(session_factory=_session_factory)

    reply = service.turn(_turn_params(root, create_session=True))

    assert reply["text"].startswith("No LLM provider is configured")


def test_second_turn_on_existing_session_omits_no_provider_notice(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    service = LspConversationService(session_factory=_session_factory)

    first_reply = service.turn(_turn_params(root, create_session=True))
    second_reply = service.turn(_turn_params(root, create_session=False))

    assert first_reply["text"].startswith("No LLM provider is configured")
    assert "No LLM provider is configured" not in second_reply["text"]


def test_registry_expires_idle_sessions(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    now = [0.0]
    service = LspConversationService(
        session_factory=_session_factory,
        clock=lambda: now[0],
    )
    service.turn(_turn_params(root, create_session=True))
    now[0] = 1801.0

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, create_session=False))


def test_registry_keeps_exact_boundary_and_expires_immediately_after(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    now = [0.0]
    service = LspConversationService(
        session_factory=_session_factory,
        clock=lambda: now[0],
    )
    service.turn(_turn_params(root, create_session=True))
    now[0] = 1800.0

    assert service.turn(_turn_params(root, create_session=False))["kind"] == "answer"

    now[0] = 3600.001
    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, create_session=False))


def test_registry_evicts_the_least_recently_used_session(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    now = [0.0]
    service = LspConversationService(
        max_sessions=2,
        session_factory=_session_factory,
        clock=lambda: now[0],
    )
    service.turn(_turn_params(root, session_id="session-1", create_session=True))
    now[0] = 1.0
    service.turn(_turn_params(root, session_id="session-2", create_session=True))
    now[0] = 2.0
    service.turn(_turn_params(root, session_id="session-1", create_session=False))
    now[0] = 3.0
    service.turn(_turn_params(root, session_id="session-3", create_session=True))

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, session_id="session-2", create_session=False))

    assert service.turn(_turn_params(root, session_id="session-1", create_session=False))["kind"] == "answer"


def test_registry_caps_sessions_at_32_and_evicts_the_lru_id(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    now = [0.0]
    service = LspConversationService(
        session_factory=_session_factory,
        clock=lambda: now[0],
    )
    for number in range(1, 32):
        now[0] = float(number)
        service.turn(
            _turn_params(
                root,
                session_id=f"session-{number}",
                create_session=True,
            )
        )
    now[0] = 32.0
    service.turn(_turn_params(root, session_id="session-1", create_session=False))
    now[0] = 33.0
    service.turn(_turn_params(root, session_id="session-32", create_session=True))
    now[0] = 34.0
    service.turn(_turn_params(root, session_id="session-33", create_session=True))

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, session_id="session-2", create_session=False))

    assert service.turn(_turn_params(root, session_id="session-1", create_session=False))["kind"] == "answer"


def test_registry_binds_sessions_and_filters_dirty_files_by_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = _write_customer_workspace(root)
    other_root = tmp_path / "other"
    other_source = _write_customer_workspace(other_root)
    service = LspConversationService(session_factory=_session_factory)
    service.turn(_turn_params(root, create_session=True))

    with pytest.raises(ConversationSessionError, match="different workspace"):
        service.turn(
            _turn_params(
                other_root,
                create_session=False,
            )
        )

    with pytest.raises(ConversationSessionError, match="Save these files"):
        service.turn(
            _turn_params(
                root,
                create_session=False,
                dirty_document_uris=(source.as_uri(),),
            )
        )

    reply = service.turn(
        _turn_params(
            root,
            create_session=False,
            dirty_document_uris=(other_source.as_uri(),),
        )
    )

    assert reply["kind"] == "answer"


def test_registry_rejects_duplicate_creation_and_updates_focus(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = _write_customer_workspace(root)
    (root / "workspace.mdl").write_text('workspace "example" {}\n', encoding="utf-8")
    index = LspWorkspaceIndex()
    index.upsert_document(source.as_uri(), source.read_text(encoding="utf-8"))
    sessions: list[ConversationSession] = []

    def capture_session(root: Path, focused_ref: str | None) -> ConversationSession:
        session = _session_factory(root, focused_ref)
        sessions.append(session)
        return session

    params = _turn_params(root, create_session=True).model_copy(
        update={
            "active_document_uri": source.as_uri(),
            "position": ConversationPosition(line=3, character=8),
        }
    )
    service = LspConversationService(session_factory=capture_session)

    reply = service.turn(params, index=index)

    assert sessions[0].focused_ref == "customer.Customer@1"
    assert reply["focusedRef"] == "customer.Customer@1"
    with pytest.raises(ConversationSessionError, match="already exists"):
        service.turn(params, index=index)


def test_registry_resolves_nested_active_root_and_manifestless_fallback(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    nested = root / "domains" / "customer"
    source = _write_customer_workspace(nested)
    (root / "workspace.mdl").write_text('workspace default { name: "example" }\n', encoding="utf-8")
    service = LspConversationService(session_factory=_session_factory)
    nested_params = _turn_params(root, create_session=True).model_copy(update={"active_document_uri": source.as_uri()})

    reply = service.turn(nested_params)

    assert reply["workspaceUri"] == root.as_uri()

    fallback = tmp_path / "fallback"
    fallback_source = _write_customer_workspace(fallback)
    fallback_service = LspConversationService(session_factory=_session_factory)
    fallback_reply = fallback_service.turn(
        _turn_params(fallback, create_session=True).model_copy(update={"active_document_uri": fallback_source.as_uri()})
    )
    assert fallback_reply["kind"] == "answer"


def test_registry_rejects_malformed_workspace_uri(tmp_path: Path) -> None:
    params = _turn_params(tmp_path, create_session=True).model_copy(
        update={"workspace_uri": "https://example.com/workspace"}
    )

    with pytest.raises(ConversationSessionError, match="file URI"):
        LspConversationService(session_factory=_session_factory).turn(params)


def test_registry_binds_and_reuses_session_documentation_index(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    docs_index = _make_documentation_index(root)
    service = LspConversationService(session_factory=_session_factory)

    service.turn(
        _turn_params(root, create_session=True).model_copy(update={"documentation_index_uri": docs_index.as_uri()})
    )

    entry = service._sessions["session-1"]
    assert entry.documentation_index_uri == docs_index.resolve().as_uri()
    assert isinstance(entry.documentation_retriever, DocumentationRetriever)
    first_retriever = entry.documentation_retriever

    service.turn(_turn_params(root, create_session=False))
    service.turn(
        _turn_params(root, create_session=False).model_copy(update={"documentation_index_uri": docs_index.as_uri()})
    )

    assert service._sessions["session-1"].documentation_index_uri == docs_index.resolve().as_uri()
    assert service._sessions["session-1"].documentation_retriever is first_retriever


def test_registry_rejects_documentation_index_outside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    external_index = _make_documentation_index(tmp_path / "outside")
    service = LspConversationService(session_factory=_session_factory)

    with pytest.raises(ConversationSessionError, match="workspace"):
        service.turn(
            _turn_params(root, create_session=True).model_copy(
                update={"documentation_index_uri": external_index.as_uri()}
            )
        )

    assert "session-1" not in service._sessions


@pytest.mark.parametrize("section", ["terms", "docs", "facets", "pins", "synonyms", "fuzzy", "vectors"])
def test_registry_rejects_documentation_shard_traversal_outside_workspace(
    tmp_path: Path,
    section: str,
) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    docs_index = _make_documentation_index(root)
    outside_shard = tmp_path / "outside-docs.json"
    outside_shard.write_text('{"outside": "secret"}', encoding="utf-8")
    _replace_manifest_shard_file(docs_index, section, "../../outside-docs.json")
    service = LspConversationService(session_factory=_session_factory)

    with pytest.raises(ConversationSessionError, match="workspace"):
        service.turn(
            _turn_params(root, create_session=True).model_copy(update={"documentation_index_uri": docs_index.as_uri()})
        )

    assert "session-1" not in service._sessions


def test_registry_rejects_symlinked_documentation_shard_outside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    docs_index = _make_documentation_index(root)
    manifest = json.loads(docs_index.read_text(encoding="utf-8"))
    original_shard = docs_index.parent / manifest["shards"]["docs"][0]["file"]
    outside_shard = tmp_path / "outside-docs.json"
    outside_shard.write_bytes(original_shard.read_bytes())
    linked_shard = original_shard.with_name("outside-link.json")
    try:
        linked_shard.symlink_to(outside_shard)
    except NotImplementedError as error:
        pytest.skip(f"platform cannot create symlinks: {error}")
    except OSError as error:
        if error.errno not in {errno.EACCES, errno.EPERM, errno.ENOTSUP} and getattr(error, "winerror", None) != 1314:
            raise
        pytest.skip(f"platform cannot create symlinks: {error}")
    _replace_manifest_shard_file(
        docs_index,
        "docs",
        linked_shard.relative_to(docs_index.parent).as_posix(),
    )
    service = LspConversationService(session_factory=_session_factory)

    with pytest.raises(ConversationSessionError, match="workspace"):
        service.turn(
            _turn_params(root, create_session=True).model_copy(update={"documentation_index_uri": docs_index.as_uri()})
        )

    assert "session-1" not in service._sessions


def test_registry_rejects_documentation_index_mutation_for_existing_session(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    first_index = _make_documentation_index(root / "first")
    second_index = _make_documentation_index(root / "second")

    class RecordingSession:
        def __init__(self, **kwargs) -> None:
            self.no_provider_notice = None
            self.focused_ref = kwargs.get("focused_ref")
            self.workspace = load_workspace(root)
            self.messages: list[str] = []

        def turn(self, message: str):
            self.messages.append(message)
            return type(
                "Reply",
                (),
                {
                    "kind": "answer",
                    "text": "session reply",
                    "change_set_id": None,
                    "operation_kind": None,
                    "focused_ref": self.focused_ref,
                    "changed": (),
                    "affected": (),
                    "compatibility": (),
                    "diagnostics": (),
                    "preview_files": (),
                    "compilation_files": (),
                    "registry_id_changes": (),
                    "audit_path": None,
                    "written_paths": (),
                },
            )()

        def close(self) -> None:
            return None

    created: list[RecordingSession] = []

    def session_factory(root: Path, focused_ref: str | None):
        session = RecordingSession(root=root, focused_ref=focused_ref)
        created.append(session)
        return session

    service = LspConversationService(session_factory=session_factory)
    service.turn(
        _turn_params(root, create_session=True).model_copy(update={"documentation_index_uri": first_index.as_uri()})
    )
    entry = service._sessions["session-1"]
    first_retriever = entry.documentation_retriever

    with pytest.raises(ConversationSessionError, match="documentation index"):
        service.turn(
            _turn_params(root, create_session=False).model_copy(
                update={"documentation_index_uri": second_index.as_uri()}
            )
        )

    assert created[0].messages == ["is the workspace valid?"]
    assert service._sessions["session-1"].documentation_index_uri == first_index.resolve().as_uri()
    assert service._sessions["session-1"].documentation_retriever is first_retriever


def test_lsp_docs_turn_returns_citations_without_edit_side_effects(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    index_uri = _make_documentation_index(root).as_uri()

    class DocsProvider:
        def complete(self, request: object) -> LLMResponse:
            return LLMResponse(content="Use [S1] to install it.", provider="fake", model="test")

    class RecordingSession:
        def __init__(self, **kwargs) -> None:
            self.provider = DocsProvider()
            self.no_provider_notice = None
            self.focused_ref = kwargs.get("focused_ref")
            self.workspace = load_workspace(root)
            self.messages: list[str] = []

        def turn(self, message: str) -> ConversationReply:
            self.messages.append(message)
            return ConversationReply(kind="answer", text="session reply", focused_ref=self.focused_ref)

        def close(self) -> None:
            return None

    created: list[RecordingSession] = []

    def session_factory(root: Path, focused_ref: str | None):
        session = RecordingSession(root=root, focused_ref=focused_ref)
        created.append(session)
        return session

    service = LspConversationService(session_factory=session_factory)

    reply = service.turn(
        _turn_params(root, create_session=True).model_copy(
            update={
                "message": "/docs install",
                "documentation_index_uri": index_uri,
            }
        )
    )

    assert reply["kind"] == "answer"
    assert "Sources:" in reply["text"]
    assert "[S1]" in reply["text"]
    assert "guide.md#install" in reply["text"]
    assert reply["changeSetId"] is None
    assert reply["retrievalUsed"] is True
    assert reply["routeReason"] == "explicit_docs_command"
    assert reply["citations"][0]["label"] == "S1"
    assert reply["citations"][0]["externalId"] == "guide.md#install"
    assert reply["citations"][0]["url"] == "https://example.test/guide/#install"
    assert reply["citations"][0]["title"] == "Guide"
    assert reply["citations"][0]["heading"] == "Install"
    assert reply["citations"][0]["score"] > 0
    assert created[0].messages == []


def test_lsp_automatic_documentation_defaults_enabled_with_index(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    index_uri = _make_documentation_index(root).as_uri()

    class DocsProvider:
        def complete(self, request: object) -> LLMResponse:
            return LLMResponse(content="Use [S1] to configure it.", provider="fake", model="test")

    class RecordingSession:
        def __init__(self, **kwargs) -> None:
            self.provider = DocsProvider()
            self.no_provider_notice = None
            self.focused_ref = kwargs.get("focused_ref")
            self.workspace = load_workspace(root)
            self.messages: list[str] = []

        def turn(self, message: str) -> ConversationReply:
            self.messages.append(message)
            return ConversationReply(kind="answer", text="planner answer", focused_ref=self.focused_ref)

        def close(self) -> None:
            return None

    created: list[RecordingSession] = []

    def session_factory(root: Path, focused_ref: str | None):
        session = RecordingSession(root=root, focused_ref=focused_ref)
        created.append(session)
        return session

    service = LspConversationService(session_factory=session_factory)

    reply = service.turn(
        _turn_params(root, create_session=True).model_copy(
            update={
                "message": "How do I configure install?",
                "documentation_index_uri": index_uri,
            }
        )
    )

    assert reply["text"].startswith("Use [S1] to configure it.")
    assert reply["retrievalUsed"] is True
    assert reply["routeReason"] == "automatic_documentation_signal"
    assert reply["citations"][0]["externalId"] == "guide.md#install"
    assert created[0].messages == []


def test_lsp_explicit_docs_works_with_automatic_documentation_disabled(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    index_uri = _make_documentation_index(root).as_uri()

    class DocsProvider:
        def complete(self, request: object) -> LLMResponse:
            return LLMResponse(content="Explicit answer. [S1]", provider="fake", model="test")

    class RecordingSession:
        provider = DocsProvider()
        no_provider_notice = None
        focused_ref = None
        workspace = load_workspace(root)

        def turn(self, message: str) -> ConversationReply:
            return ConversationReply(kind="answer", text="planner answer")

        def close(self) -> None:
            return None

    params = ConversationTurnParams.model_validate(
        {
            "protocolVersion": 2,
            "sessionId": "session-1",
            "createSession": True,
            "workspaceUri": root.as_uri(),
            "message": "/docs install",
            "documentationIndexUri": index_uri,
            "automaticDocumentation": False,
            "dirtyDocumentUris": [],
        }
    )

    reply = LspConversationService(session_factory=lambda *_args: RecordingSession()).turn(params)

    assert reply["text"].startswith("Explicit answer. [S1]")
    assert reply["routeReason"] == "explicit_docs_command"


def test_lsp_automatic_retrieval_failure_falls_back_to_session(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    index_uri = _make_documentation_index(root).as_uri()
    retrieval_queries: list[str] = []

    def fail_search(self: DocumentationRetriever, query: str, *, limit: int = 8):
        retrieval_queries.append(query)
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(DocumentationRetriever, "search", fail_search)

    class RecordingSession:
        provider = object()
        no_provider_notice = None
        focused_ref = None
        workspace = load_workspace(root)

        def __init__(self) -> None:
            self.messages: list[str] = []

        def turn(self, message: str) -> ConversationReply:
            self.messages.append(message)
            return ConversationReply(kind="answer", text="planner fallback")

        def close(self) -> None:
            return None

    session = RecordingSession()
    service = LspConversationService(session_factory=lambda *_args: session)

    reply = service.turn(
        _turn_params(root, create_session=True).model_copy(
            update={
                "message": "How do I configure the command?",
                "documentation_index_uri": index_uri,
            }
        )
    )

    assert reply["text"] == "planner fallback"
    assert {"retrievalUsed", "citations", "routeReason"}.isdisjoint(reply)
    assert retrieval_queries == ["How do I configure the command?"]
    assert session.messages == ["How do I configure the command?"]


def test_lsp_mutation_documentation_text_never_calls_retriever(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    index_uri = _make_documentation_index(root).as_uri()

    def reject_search(self: DocumentationRetriever, query: str, *, limit: int = 8):
        raise AssertionError("mutation text must not retrieve documentation")

    monkeypatch.setattr(DocumentationRetriever, "search", reject_search)

    class RecordingSession:
        provider = object()
        no_provider_notice = None
        focused_ref = None
        workspace = load_workspace(root)

        def __init__(self) -> None:
            self.messages: list[str] = []

        def turn(self, message: str) -> ConversationReply:
            self.messages.append(message)
            return ConversationReply(kind="answer", text="mutation planner")

        def close(self) -> None:
            return None

    session = RecordingSession()
    service = LspConversationService(session_factory=lambda *_args: session)

    reply = service.turn(
        _turn_params(root, create_session=True).model_copy(
            update={
                "message": "Add a documentation model",
                "documentation_index_uri": index_uri,
            }
        )
    )

    assert reply["text"] == "mutation planner"
    assert {"retrievalUsed", "citations", "routeReason"}.isdisjoint(reply)
    assert session.messages == ["Add a documentation model"]


def test_lsp_docs_without_index_returns_missing_index_guidance_without_provider_notice(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    monkeypatch.setattr(
        "modelable.lsp.conversation_service.bundled_documentation_index_path",
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    service = LspConversationService(session_factory=_session_factory)

    reply = service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "/docs install"}))

    assert reply["kind"] == "answer"
    assert reply["text"] == "The /docs command requires --docs-index to be configured."
    assert "No LLM provider is configured" not in reply["text"]


def test_lsp_docs_uses_bundled_index_by_default(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    bundled = tmp_path / "bundled" / "manifest.json"
    bundled.parent.mkdir(parents=True)
    build_documentation_index(
        [
            DocumentationChunk(
                external_id="guide.md#install",
                source_path="guide.md",
                url="https://example.test/guide/#install",
                language="en",
                title="Guide",
                heading="Install",
                heading_path=["Guide", "Install"],
                content="How do I configure install? Install with uv.",
                chunk_index=0,
            )
        ],
        bundled.parent,
    )
    monkeypatch.setattr(
        "modelable.lsp.conversation_service.bundled_documentation_index_path",
        lambda: bundled,
    )

    class DocsProvider:
        def complete(self, request: object) -> LLMResponse:
            return LLMResponse(content="Use [S1] to install it.", provider="fake", model="test")

    class RecordingSession:
        def __init__(self, **kwargs) -> None:
            self.provider = DocsProvider()
            self.no_provider_notice = None
            self.focused_ref = kwargs.get("focused_ref")
            self.workspace = load_workspace(root)
            self.messages: list[str] = []

        def turn(self, message: str) -> ConversationReply:
            self.messages.append(message)
            return ConversationReply(kind="answer", text="planner answer", focused_ref=self.focused_ref)

        def close(self) -> None:
            return None

    def session_factory(root: Path, focused_ref: str | None, **kwargs):
        return RecordingSession(root=root, focused_ref=focused_ref)

    service = LspConversationService(session_factory=session_factory)
    reply = service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "/docs install"}))

    assert reply["kind"] == "answer"
    assert reply["retrievalUsed"] is True
    assert "Use [S1] to install it." in reply["text"]


def test_lsp_docs_provider_failure_is_an_answer_and_session_survives(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    index_uri = _make_documentation_index(root).as_uri()

    class FailingDocsProvider:
        def complete(self, request: object) -> LLMResponse:
            raise RuntimeError("documentation provider unavailable")

    class RecordingSession:
        def __init__(self, **kwargs) -> None:
            self.provider = FailingDocsProvider()
            self.no_provider_notice = None
            self.focused_ref = kwargs.get("focused_ref")
            self.workspace = load_workspace(root)
            self.messages: list[str] = []

        def turn(self, message: str) -> ConversationReply:
            self.messages.append(message)
            return ConversationReply(kind="answer", text="session reply", focused_ref=self.focused_ref)

        def close(self) -> None:
            return None

    created: list[RecordingSession] = []

    def session_factory(root: Path, focused_ref: str | None):
        session = RecordingSession(root=root, focused_ref=focused_ref)
        created.append(session)
        return session

    service = LspConversationService(session_factory=session_factory)

    failed = service.turn(
        _turn_params(root, create_session=True).model_copy(
            update={
                "message": "/docs install",
                "documentation_index_uri": index_uri,
            }
        )
    )
    normal = service.turn(_turn_params(root, create_session=False))

    assert failed["kind"] == "answer"
    assert failed["changeSetId"] is None
    assert "configured provider failed during the documentation answer request" in failed["text"]
    assert "documentation provider unavailable" in failed["text"]
    assert normal["kind"] == "answer"
    assert normal["text"] == "session reply"
    assert created[0].messages == ["is the workspace valid?"]


def test_registry_reports_provider_configuration_failure(tmp_path: Path) -> None:
    _write_customer_workspace(tmp_path)
    (tmp_path / "workspace.mdl").write_text(
        'workspace default {\n  name: "example"\n  ai {\n    provider: "unsupported-provider"\n  }\n}\n',
        encoding="utf-8",
    )

    with pytest.raises(ConversationSessionError, match="provider configuration"):
        LspConversationService().turn(_turn_params(tmp_path, create_session=True))


def test_registry_close_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    service = LspConversationService(session_factory=_session_factory)
    service.turn(_turn_params(root, create_session=True))

    service.close("session-1")
    service.close("session-1")

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, create_session=False))


class _CompileProvider:
    def complete(self, request: LLMRequest) -> LLMResponse:
        plan = CompilePlan(
            target="rust",
            summary="Compile to Rust.",
        )
        return LLMResponse(
            content=plan.model_dump_json(),
            provider="lsp-provider",
            model="lsp-model",
        )


def test_registry_close_disposes_compilation_staging(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    sessions: list[ConversationSession] = []

    def compile_session(root: Path, focused_ref: str | None) -> ConversationSession:
        session = ConversationSession(
            path=root,
            provider=_CompileProvider(),
            focused_ref=focused_ref,
            compilation_service=CompilationService(temp_root=tmp_path),
        )
        sessions.append(session)
        return session

    service = LspConversationService(session_factory=compile_session)
    service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "compile to rust"}))
    pending = sessions[0].pending
    assert isinstance(pending, PendingCompilation)

    service.close("session-1")

    assert not pending.staging_dir.exists()


def test_registry_expiry_disposes_compilation_staging(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    now = [0.0]
    sessions: list[ConversationSession] = []

    def compile_session(root: Path, focused_ref: str | None) -> ConversationSession:
        session = ConversationSession(
            path=root,
            provider=_CompileProvider(),
            focused_ref=focused_ref,
            compilation_service=CompilationService(temp_root=tmp_path),
        )
        sessions.append(session)
        return session

    service = LspConversationService(
        session_factory=compile_session,
        clock=lambda: now[0],
    )
    service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "compile to rust"}))
    pending = sessions[0].pending
    assert isinstance(pending, PendingCompilation)
    now[0] = 1801.0

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, create_session=False))

    assert not pending.staging_dir.exists()


def test_registry_lru_eviction_disposes_compilation_staging(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    sessions: list[ConversationSession] = []

    def compile_session(root: Path, focused_ref: str | None) -> ConversationSession:
        session = ConversationSession(
            path=root,
            provider=_CompileProvider(),
            focused_ref=focused_ref,
            compilation_service=CompilationService(temp_root=tmp_path),
        )
        sessions.append(session)
        return session

    service = LspConversationService(max_sessions=1, session_factory=compile_session)
    service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "compile to rust"}))
    pending = sessions[0].pending
    assert isinstance(pending, PendingCompilation)

    service.turn(_turn_params(root, session_id="session-2", create_session=True))

    assert not pending.staging_dir.exists()


def test_lsp_compile_apply_uses_protocol_v2(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)

    def compile_session(root: Path, focused_ref: str | None) -> ConversationSession:
        return ConversationSession(
            path=root,
            provider=_CompileProvider(),
            focused_ref=focused_ref,
            compilation_service=CompilationService(temp_root=tmp_path),
        )

    service = LspConversationService(session_factory=compile_session)
    preview = service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "compile to rust"}))
    action_id = preview["changeSetId"]
    assert isinstance(action_id, str)
    assert (
        preview["auditUri"] == (root / ".modelable" / "audit" / "compilations" / f"{action_id}.json").resolve().as_uri()
    )

    reply = service.apply(
        _change_set_params(
            session_id="session-1",
            change_set_id=action_id,
        )
    )

    assert reply["kind"] == "applied"
    assert reply["operationKind"] == "compile"
    assert reply["changeSetId"] == action_id
    assert reply["auditUri"] is not None


def test_lsp_compile_apply_rejects_dirty_generated_destination(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    sessions: list[ConversationSession] = []

    def compile_session(root: Path, focused_ref: str | None) -> ConversationSession:
        session = ConversationSession(
            path=root,
            provider=_CompileProvider(),
            focused_ref=focused_ref,
            compilation_service=CompilationService(temp_root=tmp_path),
        )
        sessions.append(session)
        return session

    service = LspConversationService(session_factory=compile_session)
    preview = service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "compile to rust"}))
    action_id = preview["changeSetId"]
    pending = sessions[0].pending
    assert isinstance(action_id, str)
    assert isinstance(pending, PendingCompilation)
    destination = pending.files[0].destination

    with pytest.raises(
        ConversationSessionError,
        match=r"^Save generated files before applying the compilation: ",
    ) as error:
        service.apply(
            _change_set_params(
                session_id="session-1",
                change_set_id=action_id,
                dirty_document_uris=(destination.as_uri(),),
            )
        )

    assert str(destination) in str(error.value)
    service.discard(_change_set_params(session_id="session-1", change_set_id=action_id))


def test_lsp_compile_apply_rejects_dirty_planned_audit_destination(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    sessions: list[ConversationSession] = []

    def compile_session(root: Path, focused_ref: str | None) -> ConversationSession:
        session = ConversationSession(
            path=root,
            provider=_CompileProvider(),
            focused_ref=focused_ref,
            compilation_service=CompilationService(temp_root=tmp_path),
        )
        sessions.append(session)
        return session

    service = LspConversationService(session_factory=compile_session)
    preview = service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "compile to rust"}))
    action_id = preview["changeSetId"]
    pending = sessions[0].pending
    assert isinstance(action_id, str)
    assert isinstance(pending, PendingCompilation)
    audit_path = root / ".modelable" / "audit" / "compilations" / f"{action_id}.json"
    assert not audit_path.exists()

    with pytest.raises(
        ConversationSessionError,
        match=r"^Save generated files before applying the compilation: ",
    ) as error:
        service.apply(
            _change_set_params(
                session_id="session-1",
                change_set_id=action_id,
                dirty_document_uris=(audit_path.as_uri(),),
            )
        )

    assert str(audit_path.resolve()) in str(error.value)
    assert sessions[0].pending is pending
    service.discard(_change_set_params(session_id="session-1", change_set_id=action_id))


def test_lsp_compile_apply_allows_dirty_unrelated_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    unrelated = _write_customer_workspace(root)

    def compile_session(root: Path, focused_ref: str | None) -> ConversationSession:
        return ConversationSession(
            path=root,
            provider=_CompileProvider(),
            focused_ref=focused_ref,
            compilation_service=CompilationService(temp_root=tmp_path),
        )

    service = LspConversationService(session_factory=compile_session)
    preview = service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "compile to rust"}))
    action_id = preview["changeSetId"]
    assert isinstance(action_id, str)

    reply = service.apply(
        _change_set_params(
            session_id="session-1",
            change_set_id=action_id,
            dirty_document_uris=(unrelated.as_uri(),),
        )
    )

    assert reply["kind"] == "applied"


def test_default_lsp_session_uses_real_vscode_confirmation_provenance(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    service = LspConversationService()

    service.turn(
        _turn_params(root, session_id="real-vscode-session", create_session=True).model_copy(
            update={"message": "/compile rust"}
        )
    )
    session = service._sessions["real-vscode-session"].session

    applied = session.turn("/apply")

    assert applied.audit_path is not None
    audit = json.loads(applied.audit_path.read_text(encoding="utf-8"))
    assert audit["sessionId"] == "real-vscode-session"
    assert audit["confirmation"]["surface"] == "vscode-chat"
    assert audit["confirmation"]["model"] == "modelable-local"


class _CreateAccountProvider:
    def complete(self, request: LLMRequest) -> LLMResponse:
        plan = ChangeSetPlan(
            summary="Create customer.Account@1",
            operations=[
                CreateModel(
                    domain="customer",
                    name="Account",
                    model_kind="entity",
                    fields=[
                        FieldSpec(
                            name="accountId",
                            type=PrimitiveType(kind="uuid"),
                            annotations=[AnnKey()],
                        )
                    ],
                )
            ],
        )
        return LLMResponse(
            content=plan.model_dump_json(),
            provider="fake",
            model="test-model",
        )


def _editing_session_factory(root: Path, focused_ref: str | None) -> ConversationSession:
    return ConversationSession(
        path=root,
        provider=_CreateAccountProvider(),
        focused_ref=focused_ref,
    )


def _change_set_params(
    *,
    session_id: str,
    change_set_id: str,
    dirty_document_uris: tuple[str, ...] = (),
) -> ConversationChangeSetParams:
    return ConversationChangeSetParams.model_validate(
        {
            "protocolVersion": 2,
            "sessionId": session_id,
            "changeSetId": change_set_id,
            "dirtyDocumentUris": list(dirty_document_uris),
        }
    )


def test_apply_requires_the_exact_pending_change_set_id(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = _write_customer_workspace(root)
    service = LspConversationService(session_factory=_editing_session_factory)
    preview = service.turn(
        _turn_params(root, create_session=True).model_copy(update={"message": "add an account entity"})
    )
    change_set_id = preview["changeSetId"]
    assert isinstance(change_set_id, str)

    with pytest.raises(ConversationSessionError, match="current pending action"):
        service.apply(
            _change_set_params(
                session_id="session-1",
                change_set_id="wrong-id",
            )
        )
    with pytest.raises(ConversationSessionError, match="Save these files"):
        service.apply(
            _change_set_params(
                session_id="session-1",
                change_set_id=change_set_id,
                dirty_document_uris=(source.as_uri(),),
            )
        )

    reply = service.apply(
        _change_set_params(
            session_id="session-1",
            change_set_id=change_set_id,
        )
    )

    assert reply["kind"] == "applied"
    assert reply["changeSetId"] == change_set_id
    assert source.as_uri() in reply["writtenPaths"]


def test_discard_requires_the_exact_pending_change_set_id(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = _write_customer_workspace(root)
    service = LspConversationService(session_factory=_editing_session_factory)
    preview = service.turn(
        _turn_params(root, create_session=True).model_copy(update={"message": "add an account entity"})
    )
    change_set_id = preview["changeSetId"]
    assert isinstance(change_set_id, str)

    with pytest.raises(ConversationSessionError, match="current pending action"):
        service.discard(
            _change_set_params(
                session_id="session-1",
                change_set_id="wrong-id",
            )
        )
    with pytest.raises(ConversationSessionError, match="Save these files"):
        service.discard(
            _change_set_params(
                session_id="session-1",
                change_set_id=change_set_id,
                dirty_document_uris=(source.as_uri(),),
            )
        )

    reply = service.discard(
        _change_set_params(
            session_id="session-1",
            change_set_id=change_set_id,
        )
    )

    assert reply["kind"] == "discarded"
    assert reply["changeSetId"] == change_set_id
