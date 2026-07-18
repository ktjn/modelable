# VS Code Conversational Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native `@modelable` VS Code chat participant that exposes the shipped conversational workspace-management service through versioned language-server requests.

**Architecture:** The extension remains a presentation-only client over a protocol-versioned Python application service. Python owns provider configuration, typed planning, focus resolution, validation, exact previews, session state, stale detection, atomic writes, rollback, and reload; VS Code owns chat history integration, dirty-buffer discovery, Markdown/anchor rendering, follow-up actions, and built-in diff presentation.

**Tech Stack:** Python 3.11+, Pydantic, pygls/lsprotocol, pytest/pytest-lsp, VS Code Extension API 1.125, CommonJS JavaScript, TypeScript 7 test compilation, Mocha, `vscode-languageclient` 10.1.

## Global Constraints

- Implement [VS Code Conversational Foundation — Design](../../specs/archived/2026-07-18-vscode-conversational-foundation-design.md) exactly.
- Use participant ID `modelable-vscode.modelable`.
- Use custom protocol version `1`; reject absent, malformed, or unsupported versions.
- Use the existing `resolve_llm_config` and `build_provider` Python functions. Add no VS Code-specific Modelable provider settings.
- Keep `.mdl` parsing, focus resolution, typed planning, rendering, validation, compatibility, impact analysis, fingerprinting, writes, rollback, and reload in Python.
- Refuse turn and apply requests while any `.mdl` document under the resolved Modelable root is dirty.
- Apply and discard must include the exact current change-set ID.
- Serialize available definition locations in Python so VS Code can render
  anchors without resolving refs in JavaScript.
- Apply and discard UI actions are native chat follow-ups; only View Diff is a VS Code command button.
- Use exact before/after snapshots in the built-in diff editor; never apply a VS Code `WorkspaceEdit`.
- Cap the server registry at 32 sessions and expire sessions after 30 minutes of inactivity.
- Do not log prompts, history, model responses, source summaries, diffs, preview snapshots, credentials, or source-bearing diagnostics by default.
- Add no new runtime dependency in `cli/` or `vscode/`.
- Preserve `vscode.engines.vscode` at `^1.125.0`.
- Retain the optional VS Code Language Model API provider adapter as a future
  roadmap item; it is not part of this implementation.
- Run the four commands required by `AGENTS.md` from `cli/` before every commit.
- Run `npm run check`, `npm run build`, `npm test`, and `npm run package` from `vscode/` before commits that change the extension.

## Planned File Structure

- `cli/src/modelable/llm/conversation.py` — enrich shared replies with structured preview and apply data.
- `cli/src/modelable/lsp/conversation_protocol.py` — versioned request models and JSON reply serialization.
- `cli/src/modelable/lsp/conversation_service.py` — workspace/focus resolution, provider construction, bounded session registry, and operation dispatch.
- `cli/src/modelable/lsp/workspace.py` — expose shared workspace-root lookup.
- `cli/src/modelable/lsp/document_symbols.py` — expose cursor-to-definition focus lookup.
- `cli/src/modelable/lsp/definition.py` — expose canonical ref-to-location lookup for reply anchors.
- `cli/src/modelable/lsp/server.py` — advertise the capability and register four custom methods.
- `cli/tests/test_conversation.py` — structured shared-reply behavior.
- `cli/tests/test_lsp_conversation_protocol.py` — closed request schema and serializer behavior.
- `cli/tests/test_lsp_conversation_service.py` — registry, focus, dirty, expiry, and exact-ID behavior.
- `cli/tests/test_lsp_conversation_integration.py` — real JSON-RPC request flow.
- `vscode/conversationClient.js` — metadata recovery, editor context, dirty documents, requests, and cancellation cleanup.
- `vscode/conversationPreview.js` — virtual snapshot documents and built-in diff routing.
- `vscode/conversationParticipant.js` — chat handler, rendering, follow-ups, and reset.
- `vscode/extension.js` — language-client startup plus participant registration.
- `vscode/package.json` — participant contribution, activation, and View Diff command.
- `vscode/src/test/suite/conversation.test.ts` — extension-side behavior.
- `vscode/README.md`, `docs/architecture.md`, `docs/cli-reference.md`, `CHANGELOG.md`, `ROADMAP.md` — user and architecture documentation.

---

### Task 1: Expose Structured Conversation Results

**Files:**
- Modify: `cli/src/modelable/llm/conversation.py`
- Modify: `cli/tests/test_conversation.py`

**Interfaces:**
- Consumes: existing `ConversationSession`, `PendingChangeSet`, `AppliedChangeSet`, `ChangedDefinition`, `AffectedDefinition`, `CompatibilityFinding`, and `Diagnostic`.
- Produces: `ConversationPreviewFile` and enriched `ConversationReply` fields used by the language-server serializer in Task 2.

- [ ] **Step 1: Add failing preview-structure assertions**

Extend `test_preview_and_apply_complete_entity`:

```python
    assert preview.changed[0].ref == "customer.Customer@1"
    assert preview.affected == ()
    assert preview.change_set_id is not None
    assert preview.preview_files == (
        ConversationPreviewFile(
            path=source,
            existed_before=True,
            before_text=original,
            after_text=preview.preview_files[0].after_text,
        ),
    )
    assert "entity Customer @ 1" in preview.preview_files[0].after_text

    applied = session.turn("apply")

    assert applied.written_paths == (source,)
    assert applied.changed[0].ref == "customer.Customer@1"
    assert applied.focused_ref == "customer.Customer@1"
```

Import `ConversationPreviewFile` beside `ConversationSession`.

- [ ] **Step 2: Verify the new assertions fail**

Run:

```bash
uv run pytest tests/test_conversation.py::test_preview_and_apply_complete_entity -v
```

Expected: failure because `ConversationReply` has no `changed`,
`preview_files`, `written_paths`, or `focused_ref` fields.

- [ ] **Step 3: Add immutable structured reply fields**

Add:

```python
@dataclass(frozen=True)
class ConversationPreviewFile:
    path: Path
    existed_before: bool
    before_text: str
    after_text: str


@dataclass(frozen=True)
class ConversationReply:
    kind: Literal[
        "answer",
        "clarification",
        "preview",
        "applied",
        "discarded",
        "unsupported",
        "error",
    ]
    text: str
    change_set_id: str | None = None
    focused_ref: str | None = None
    changed: tuple[ChangedDefinition, ...] = ()
    affected: tuple[AffectedDefinition, ...] = ()
    compatibility: tuple[CompatibilityFinding, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    preview_files: tuple[ConversationPreviewFile, ...] = ()
    written_paths: tuple[Path, ...] = ()
```

Remove the old smaller `ConversationReply` declaration.

- [ ] **Step 4: Populate preview and apply data from authoritative results**

In `_preview`, construct snapshots before returning:

```python
        current_sources = {
            source.path: source.text
            for source in self.workspace.sources
            if source.path is not None
        }
        preview_files = tuple(
            ConversationPreviewFile(
                path=path,
                existed_before=path in current_sources,
                before_text=current_sources.get(path, ""),
                after_text=after_text,
            )
            for path, after_text in sorted(pending.candidate_sources.items())
        )
```

Return:

```python
        return ConversationReply(
            kind="preview",
            text=replacement + render_pending_change_set(pending),
            change_set_id=pending.change_set_id,
            focused_ref=pending.focus_ref,
            changed=tuple(pending.changed),
            affected=tuple(pending.affected),
            compatibility=tuple(pending.compatibility),
            diagnostics=tuple(pending.diagnostics),
            preview_files=preview_files,
        )
```

Return the applied structure from `_apply_pending`:

```python
        return ConversationReply(
            kind="applied",
            text=render_applied_change_set(applied),
            change_set_id=applied.change_set_id,
            focused_ref=applied.focus_ref,
            changed=tuple(applied.changed),
            compatibility=tuple(applied.compatibility),
            written_paths=applied.written_paths,
        )
```

- [ ] **Step 5: Run conversation tests**

Run:

```bash
uv run pytest tests/test_conversation.py tests/test_llm_provider_integration.py -v
```

Expected: all selected tests pass; CLI callers continue using canonical
`reply.text`.

- [ ] **Step 6: Run the mandatory CLI gate and commit**

Run the four `AGENTS.md` commands, then:

```bash
git add cli/src/modelable/llm/conversation.py cli/tests/test_conversation.py
git commit -m "feat: expose structured conversation results"
```

---

### Task 2: Define the Versioned LSP Conversation Protocol

**Files:**
- Create: `cli/src/modelable/lsp/conversation_protocol.py`
- Create: `cli/tests/test_lsp_conversation_protocol.py`
- Modify: `cli/src/modelable/lsp/server.py`
- Modify: `cli/tests/test_lsp_server.py`

**Interfaces:**
- Consumes: enriched `ConversationReply` from Task 1.
- Produces: method constants, closed Pydantic request models,
`serialize_conversation_reply`, and initialize capability
`experimental.modelableConversation.protocolVersion == 1`.

- [ ] **Step 1: Write failing protocol-schema tests**

Create tests covering the exact closed schema:

```python
from pydantic import ValidationError
import pytest

from modelable.lsp.conversation_protocol import (
    PROTOCOL_VERSION,
    ConversationChangeSetParams,
    ConversationCloseParams,
    ConversationTurnParams,
)


def test_turn_params_require_explicit_session_creation() -> None:
    params = ConversationTurnParams.model_validate(
        {
            "protocolVersion": 1,
            "sessionId": "session-1",
            "createSession": True,
            "workspaceUri": "file:///workspace",
            "message": "describe the customer model",
            "dirtyDocumentUris": [],
        }
    )

    assert params.protocol_version == PROTOCOL_VERSION
    assert params.create_session is True


def test_turn_params_reject_unknown_fields_and_versions() -> None:
    with pytest.raises(ValidationError):
        ConversationTurnParams.model_validate(
            {
                "protocolVersion": 2,
                "sessionId": "session-1",
                "createSession": True,
                "workspaceUri": "file:///workspace",
                "message": "describe the customer model",
                "dirtyDocumentUris": [],
                "rawPatch": "delete everything",
            }
        )


def test_change_and_close_params_are_closed() -> None:
    change = ConversationChangeSetParams.model_validate(
        {
            "protocolVersion": 1,
            "sessionId": "session-1",
            "changeSetId": "change-1",
            "dirtyDocumentUris": [],
        }
    )
    close = ConversationCloseParams.model_validate(
        {"protocolVersion": 1, "sessionId": "session-1"}
    )

    assert change.change_set_id == "change-1"
    assert close.session_id == "session-1"
```

- [ ] **Step 2: Verify protocol imports fail**

Run:

```bash
uv run pytest tests/test_lsp_conversation_protocol.py -v
```

Expected: collection fails because `conversation_protocol.py` does not exist.

- [ ] **Step 3: Implement request models and method constants**

Create:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOL_VERSION = 1
TURN_METHOD = "modelable/conversation/turn"
APPLY_METHOD = "modelable/conversation/apply"
DISCARD_METHOD = "modelable/conversation/discard"
CLOSE_METHOD = "modelable/conversation/close"


class _ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    protocol_version: int = Field(alias="protocolVersion", frozen=True)

    @field_validator("protocol_version")
    @classmethod
    def require_supported_version(cls, value: int) -> int:
        if value != PROTOCOL_VERSION:
            raise ValueError(f"Unsupported Modelable conversation protocol version: {value}")
        return value


class ConversationPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: int = Field(ge=0)
    character: int = Field(ge=0)


class ConversationTurnParams(_ProtocolModel):
    session_id: str = Field(alias="sessionId", min_length=1)
    create_session: bool = Field(alias="createSession")
    workspace_uri: str = Field(alias="workspaceUri", min_length=1)
    message: str
    active_document_uri: str | None = Field(default=None, alias="activeDocumentUri")
    position: ConversationPosition | None = None
    dirty_document_uris: tuple[str, ...] = Field(default=(), alias="dirtyDocumentUris")


class ConversationChangeSetParams(_ProtocolModel):
    session_id: str = Field(alias="sessionId", min_length=1)
    change_set_id: str = Field(alias="changeSetId", min_length=1)
    dirty_document_uris: tuple[str, ...] = Field(default=(), alias="dirtyDocumentUris")


class ConversationCloseParams(_ProtocolModel):
    session_id: str = Field(alias="sessionId", min_length=1)
```

- [ ] **Step 4: Write failing reply-serialization tests**

Add a test that constructs a `ConversationReply` with a preview file,
definition impact, compatibility, and diagnostic, then asserts this exact
camel-case JSON shape:

```python
payload = serialize_conversation_reply(
    reply,
    session_id="session-1",
    workspace_uri=tmp_path.as_uri(),
)

assert payload["protocolVersion"] == 1
assert payload["kind"] == "preview"
assert payload["sessionId"] == "session-1"
assert payload["changeSetId"] == "change-1"
assert payload["previewFiles"] == [
    {
        "uri": source.resolve().as_uri(),
        "existedBefore": True,
        "beforeText": "before",
        "afterText": "after",
    }
]
assert payload["diagnostics"][0]["code"] == "SEM001"
```

- [ ] **Step 5: Implement JSON-primitive serialization**

Add:

```python
from collections.abc import Mapping

from lsprotocol import types


def serialize_conversation_reply(
    reply: ConversationReply,
    *,
    session_id: str,
    workspace_uri: str,
    definition_locations: Mapping[str, types.Location] | None = None,
) -> dict[str, object]:
    locations = definition_locations or {}
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "kind": reply.kind,
        "text": reply.text,
        "sessionId": session_id,
        "workspaceUri": workspace_uri,
        "changeSetId": reply.change_set_id,
        "focusedRef": reply.focused_ref,
        "changedDefinitions": [
            {
                "ref": item.ref,
                "reason": item.reason,
                "location": _serialize_location(locations.get(item.ref)),
            }
            for item in reply.changed
        ],
        "affectedDefinitions": [
            {
                "ref": item.ref,
                "status": item.status,
                "reason": item.reason,
                "location": _serialize_location(locations.get(item.ref)),
            }
            for item in reply.affected
        ],
        "compatibilityFindings": [
            {"ref": item.ref, "status": item.status, "message": item.message}
            for item in reply.compatibility
        ],
        "diagnostics": [_serialize_diagnostic(item) for item in reply.diagnostics],
        "previewFiles": [
            {
                "uri": item.path.resolve().as_uri(),
                "existedBefore": item.existed_before,
                "beforeText": item.before_text,
                "afterText": item.after_text,
            }
            for item in reply.preview_files
        ],
        "writtenPaths": [path.resolve().as_uri() for path in reply.written_paths],
    }
```

`_serialize_diagnostic` returns `path`, `line`, `column`, `severity`, `code`,
and `message` and no Python objects. `_serialize_location` returns `None` or a
dictionary containing `uri` and zero-based `range.start`/`range.end`
coordinates.

- [ ] **Step 6: Advertise capability version 1**

Add to `_build_initialize_result`:

```python
            experimental={
                "modelableConversation": {
                    "protocolVersion": PROTOCOL_VERSION,
                }
            },
```

Add a server test:

```python
def test_lsp_server_advertises_conversation_protocol_version() -> None:
    result = lsp_server.initialize(
        lsp_server.server,
        types.InitializeParams(capabilities=types.ClientCapabilities()),
    )

    assert result.capabilities.experimental == {
        "modelableConversation": {"protocolVersion": 1}
    }
```

- [ ] **Step 7: Run protocol/server tests and commit**

Run the focused tests, the mandatory CLI gate, then:

```bash
git add cli/src/modelable/lsp/conversation_protocol.py \
  cli/src/modelable/lsp/server.py \
  cli/tests/test_lsp_conversation_protocol.py \
  cli/tests/test_lsp_server.py
git commit -m "feat: define VS Code conversation protocol"
```

---

### Task 3: Build the Bounded Language-Server Conversation Service

**Files:**
- Create: `cli/src/modelable/lsp/conversation_service.py`
- Create: `cli/tests/test_lsp_conversation_service.py`
- Modify: `cli/src/modelable/lsp/workspace.py`
- Modify: `cli/src/modelable/lsp/server.py`
- Modify: `cli/src/modelable/lsp/document_symbols.py`
- Modify: `cli/src/modelable/lsp/definition.py`

**Interfaces:**
- Consumes: Task 2 request models and serializer; existing
`ConversationSession`, `resolve_llm_config`, `build_provider`, and
`LspWorkspaceIndex`.
- Produces: `LspConversationService.turn`, `.apply`, `.discard`, and `.close`;
public `find_workspace_root`, `find_focused_ref`, and
`definition_location_for_ref`.

- [ ] **Step 1: Test focus resolution without TypeScript parsing**

Add `find_focused_ref` tests using a loaded `LspWorkspaceIndex`:

```python
def test_find_focused_ref_returns_containing_definition(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        'domain customer {\n'
        '  owner: "customer-team"\n'
        '  entity Customer @ 1 (additive) {\n'
        '    @key customerId: uuid\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )
    index = LspWorkspaceIndex()
    index.upsert_document(source.as_uri(), source.read_text(encoding="utf-8"))

    assert find_focused_ref(index, source.as_uri(), 3, 8) == "customer.Customer@1"
    assert find_focused_ref(index, source.as_uri(), 0, 0) is None
```

- [ ] **Step 2: Implement shared root and focus helpers**

Move the existing private `_find_workspace_root` body from `server.py` into:

```python
def find_workspace_root(file_path: Path) -> Path | None:
    directory = file_path.parent
    while True:
        if (directory / "workspace.mdl").exists():
            return directory
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent
```

Update `server.py` to import and call the public helper.

In `document_symbols.py`, add:

```python
def find_focused_ref(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> str | None:
    symbols = build_document_symbols(index, uri) or []
    position = types.Position(line=line, character=character)
    for domain in symbols:
        for declaration in domain.children or []:
            if not _position_in_range(position, declaration.range):
                continue
            detail = declaration.detail or ""
            _, separator, version_text = detail.partition("@")
            if not separator or not version_text.strip().isdigit():
                return None
            return f"{domain.name}.{declaration.name}@{int(version_text.strip())}"
    return None


def _position_in_range(position: types.Position, range_: types.Range) -> bool:
    start = (range_.start.line, range_.start.character)
    current = (position.line, position.character)
    end = (range_.end.line, range_.end.character)
    return start <= current <= end
```

In `definition.py`, expose the existing qualified-ref resolver without
duplicating its scanning logic:

```python
def definition_location_for_ref(workspace, ref: str) -> types.Location | None:
    return _definition_for_qualified_ref(workspace, ref)
```

- [ ] **Step 3: Write failing registry lifecycle tests**

Use an injected clock and session factory:

```python
def test_registry_requires_create_flag_for_unknown_session(tmp_path: Path) -> None:
    service = LspConversationService(session_factory=_session_factory, clock=lambda: 10.0)

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(tmp_path, create_session=False))

    reply = service.turn(_turn_params(tmp_path, create_session=True))

    assert reply["sessionId"] == "session-1"


def test_registry_expires_idle_sessions(tmp_path: Path) -> None:
    now = [0.0]
    service = LspConversationService(session_factory=_session_factory, clock=lambda: now[0])
    service.turn(_turn_params(tmp_path, create_session=True))
    now[0] = 1801.0

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(tmp_path, create_session=False))
```

Add a separate test that creates 33 sessions, touches the first after creating
the first 31, creates sessions 32 and 33, and asserts the least-recently-used
untouched ID is the one evicted.

- [ ] **Step 4: Implement the registry and provider-backed factory**

Create:

```python
@dataclass
class _SessionEntry:
    workspace_uri: str
    session: ConversationSession
    touched_at: float


class ConversationSessionError(ValueError):
    pass


class LspConversationService:
    def __init__(
        self,
        *,
        max_sessions: int = 32,
        idle_seconds: float = 1800.0,
        clock: Callable[[], float] = time.monotonic,
        session_factory: Callable[[Path, str | None], ConversationSession] | None = None,
    ) -> None:
        self.max_sessions = max_sessions
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.session_factory = session_factory or self._build_session
        self._sessions: dict[str, _SessionEntry] = {}
```

`_build_session` must:

```python
workspace = load_workspace(root)
config = resolve_llm_config(workspace=workspace.mdl.workspace)
provider = build_provider(
    config.provider,
    model=config.model,
    base_url=config.base_url,
)
return ConversationSession(
    path=root,
    provider=provider,
    focused_ref=focused_ref,
    repair_attempts=config.repair_attempts,
)
```

Before every operation, prune entries where
`now - touched_at > idle_seconds`. Before adding a session at capacity, remove
the entry with the smallest `(touched_at, session_id)` pair.

- [ ] **Step 5: Test workspace binding and dirty-file refusal**

Add tests asserting:

```python
with pytest.raises(ConversationSessionError, match="different workspace"):
    service.turn(
        params.model_copy(
            update={
                "workspace_uri": other_root.as_uri(),
                "create_session": False,
            }
        )
    )

with pytest.raises(ConversationSessionError, match="Save these files"):
    service.turn(
        params.model_copy(
            update={"dirty_document_uris": (source.as_uri(),)}
        )
    )
```

Also assert a dirty URI outside the resolved root does not block the selected
root.

- [ ] **Step 6: Implement root, focus, and dirty filtering**

Resolve the effective root from the active document using
`find_workspace_root(active_path)` and fall back to the provided workspace URI.
Normalize paths with `Path.resolve()`. Filter dirty file URIs with
`Path.is_relative_to(root)` before refusing the operation. On each turn with a
position, call `find_focused_ref` and update `session.focused_ref` when a ref is
found.

- [ ] **Step 7: Test exact apply/discard identity**

Use a fake session with a known pending ID and assert:

```python
with pytest.raises(ConversationSessionError, match="current pending change set"):
    service.apply(_change_params(change_set_id="old-id"))

with pytest.raises(ConversationSessionError, match="current pending change set"):
    service.discard(_change_params(change_set_id="old-id"))
```

Assert the matching ID calls `session.turn("/apply")` or
`session.turn("/discard")`, serializes the result, and touches the session.

- [ ] **Step 8: Implement turn, apply, discard, and close**

`turn` creates only when `create_session` is true, rejects a duplicate create,
binds the session to one workspace, forwards the message, and serializes the
reply. `apply` and `discard` compare against `session.pending.change_set_id`
before forwarding. Before serialization, resolve locations for every changed
and affected ref with `definition_location_for_ref(session.workspace, ref)` and
pass the resulting map to `serialize_conversation_reply`. `close` uses
`dict.pop(session_id, None)` so it is idempotent.

- [ ] **Step 9: Run service tests and commit**

Run focused tests and the mandatory CLI gate, then:

```bash
git add cli/src/modelable/lsp/conversation_service.py \
  cli/src/modelable/lsp/workspace.py \
  cli/src/modelable/lsp/document_symbols.py \
  cli/src/modelable/lsp/definition.py \
  cli/src/modelable/lsp/server.py \
  cli/tests/test_lsp_conversation_service.py
git commit -m "feat: manage language-server conversation sessions"
```

---

### Task 4: Expose Conversation Operations over JSON-RPC

**Files:**
- Modify: `cli/src/modelable/lsp/server.py`
- Create: `cli/tests/test_lsp_conversation_integration.py`
- Modify: `cli/tests/test_lsp_server.py`

**Interfaces:**
- Consumes: Task 3 `LspConversationService`.
- Produces: registered `modelable/conversation/turn`, `/apply`, `/discard`,
and `/close` handlers callable by `vscode-languageclient`.

- [ ] **Step 1: Write failing handler-delegation tests**

Use a fake service on a server stub:

```python
def test_conversation_turn_validates_and_delegates() -> None:
    service = Mock()
    service.turn.return_value = {"kind": "answer", "text": "valid"}
    ls = SimpleNamespace(conversations=service, index_for=lambda uri: _Index())

    result = lsp_server.conversation_turn(
        ls,
        {
            "protocolVersion": 1,
            "sessionId": "session-1",
            "createSession": True,
            "workspaceUri": "file:///workspace",
            "message": "is the workspace valid?",
            "dirtyDocumentUris": [],
        },
    )

    assert result["kind"] == "answer"
    service.turn.assert_called_once()
```

Add equivalent tests for apply, discard, and idempotent close.

- [ ] **Step 2: Register the four handlers**

Initialize one service per server:

```python
class ModelableLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("modelable-lsp", "0.1.0")
        self.conversations = LspConversationService()
```

Register:

```python
@server.feature(TURN_METHOD)
def conversation_turn(
    ls: ModelableLanguageServer,
    payload: dict[str, object],
) -> dict[str, object]:
    params = ConversationTurnParams.model_validate(payload)
    index = (
        ls.index_for(params.active_document_uri)
        if params.active_document_uri is not None
        else None
    )
    return ls.conversations.turn(params, index=index)
```

Apply and discard validate `ConversationChangeSetParams`; close validates
`ConversationCloseParams` and returns `None`.

- [ ] **Step 3: Add a real JSON-RPC deterministic-question test**

Create a pytest-lsp fixture rooted at a temporary valid workspace and send:

```python
reply = await lsp.protocol.send_request_async(
    TURN_METHOD,
    {
        "protocolVersion": 1,
        "sessionId": "integration-session",
        "createSession": True,
        "workspaceUri": workspace_root.as_uri(),
        "message": "is the workspace valid?",
        "activeDocumentUri": source.as_uri(),
        "position": {"line": 2, "character": 10},
        "dirtyDocumentUris": [],
    },
)

assert reply["kind"] == "answer"
assert reply["sessionId"] == "integration-session"
assert reply["focusedRef"] == "customer.Customer@1"
```

- [ ] **Step 4: Add a real preview/refine/apply/discard integration test**

Start the server subprocess with deterministic provider environment values
pointing at a local test HTTP server that returns queued closed plan JSON. Send:

1. a create-entity turn;
2. a refining turn;
3. apply with the old ID and assert rejection;
4. apply with the current ID and assert `writtenPaths`;
5. another preview;
6. discard with its exact ID; and
7. a final grounded question against the reloaded workspace.

Assert source bytes remain unchanged through both previews and discard and
change only after the matching apply.

- [ ] **Step 5: Add protocol failure integration cases**

Test over real JSON-RPC:

- unsupported protocol version;
- `createSession: false` after a new server process;
- dirty source on turn;
- dirty source on apply;
- source changed after preview; and
- close followed by a non-creating turn.

Each case must return a JSON-RPC error or structured error without claiming a
write; the stale and dirty cases must preserve source bytes.

- [ ] **Step 6: Run LSP integration tests and commit**

Run:

```bash
uv run pytest tests/test_lsp_conversation_protocol.py \
  tests/test_lsp_conversation_service.py \
  tests/test_lsp_conversation_integration.py \
  tests/test_lsp_server.py -v
```

Then run the mandatory CLI gate and commit:

```bash
git add cli/src/modelable/lsp/server.py \
  cli/tests/test_lsp_server.py \
  cli/tests/test_lsp_conversation_integration.py
git commit -m "feat: expose conversational language-server requests"
```

---

### Task 5: Register the Native `@modelable` Participant

**Files:**
- Create: `vscode/conversationClient.js`
- Create: `vscode/conversationParticipant.js`
- Modify: `vscode/extension.js`
- Modify: `vscode/package.json`
- Modify: `vscode/src/test/suite/conversation.test.ts`

**Interfaces:**
- Consumes: Task 4 JSON-RPC methods and initialize capability.
- Produces: participant registration, session metadata recovery, active-editor
context, dirty-document reporting, question/preview turns, and sanitized
errors.

- [ ] **Step 1: Add manifest tests and participant contribution**

In `conversation.test.ts`, load `package.json` and assert:

```typescript
const participant = manifest.contributes.chatParticipants.find(
  (item: { id: string }) => item.id === 'modelable-vscode.modelable',
);
assert.ok(participant);
assert.strictEqual(participant.name, 'modelable');
assert.deepStrictEqual(
  participant.commands.map((item: { name: string }) => item.name),
  ['help', 'apply', 'discard', 'reset'],
);
assert.ok(
  manifest.activationEvents.includes(
    'onChatParticipant:modelable-vscode.modelable',
  ),
);
```

Add this manifest contribution:

```json
{
  "id": "modelable-vscode.modelable",
  "name": "modelable",
  "fullName": "Modelable",
  "description": "Ask about and safely manage the current Modelable workspace.",
  "isSticky": true,
  "commands": [
    {"name": "help", "description": "Show supported Modelable chat actions."},
    {"name": "apply", "description": "Apply the exact pending change set."},
    {"name": "discard", "description": "Discard the pending change set."},
    {"name": "reset", "description": "Reset the Modelable conversation session."}
  ]
}
```

- [ ] **Step 2: Test metadata recovery**

Export and test:

```javascript
function recoverSessionMetadata(history) {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const modelable = history[index]?.result?.metadata?.modelable;
    if (
      modelable?.protocolVersion === 1 &&
      typeof modelable.sessionId === 'string' &&
      typeof modelable.workspaceUri === 'string'
    ) {
      return modelable;
    }
  }
  return undefined;
}
```

Assert unrelated metadata and protocol version 2 are ignored.

- [ ] **Step 3: Test active-document and multi-root context**

With injected VS Code API fakes, cover:

- active file-language `.mdl` selects its workspace folder;
- no active model plus one folder containing `workspace.mdl` selects it;
- multiple candidate folders return an explicit ambiguity error;
- no candidate returns an open-a-model-file error; and
- every dirty `.mdl` document in the selected folder is included, while dirty
  non-model files are excluded.

- [ ] **Step 4: Implement `ConversationClient`**

Use:

```javascript
const PROTOCOL_VERSION = 1;
const TURN_METHOD = 'modelable/conversation/turn';
const APPLY_METHOD = 'modelable/conversation/apply';
const DISCARD_METHOD = 'modelable/conversation/discard';
const CLOSE_METHOD = 'modelable/conversation/close';
```

`ConversationClient.turn(request, chatContext, token)` recovers metadata or creates
`crypto.randomUUID()`, sets `createSession` accordingly, resolves editor
context, collects dirty URIs, and calls:

```javascript
return this.languageClient.sendRequest(
  TURN_METHOD,
  {
    protocolVersion: PROTOCOL_VERSION,
    sessionId,
    createSession: metadata === undefined,
    workspaceUri: context.workspaceUri.toString(),
    message,
    activeDocumentUri: context.activeDocumentUri?.toString(),
    position: context.position,
    dirtyDocumentUris: context.dirtyDocumentUris.map(uri => uri.toString()),
  },
  token,
);
```

Track all generated or recovered session IDs for deactivation cleanup. Expose
`apply(metadata, dirtyDocumentUris, token)`,
`discard(metadata, token)`, `close(sessionId)`, and `closeAll()` with exact
wire fields.

- [ ] **Step 5: Implement the first participant handler**

`registerConversationParticipant` must:

1. verify `initializeResult.capabilities.experimental.modelableConversation.protocolVersion === 1`;
2. create `vscode.chat.createChatParticipant`;
3. map ordinary prompts and `/help` to `ConversationClient.turn`;
4. stream `reply.text` with `response.markdown`;
5. return namespaced result metadata; and
6. return `ChatResult.errorDetails` with an actionable message for capability,
   context, protocol, and provider errors.

Use metadata:

```javascript
return {
  metadata: {
    modelable: {
      protocolVersion: 1,
      sessionId: reply.sessionId,
      workspaceUri: reply.workspaceUri,
      changeSetId: reply.changeSetId,
      kind: reply.kind,
    },
  },
};
```

- [ ] **Step 6: Register after the language client starts**

In `extension.js`, register only after `await nextClient.start()` and add the
participant and client cleanup disposables to `context.subscriptions`.
`deactivate` calls `conversationClient.closeAll()` before stopping the language
client.

- [ ] **Step 7: Run extension and CLI gates and commit**

Install extension dependencies with `npm ci`, run all four extension commands,
run the mandatory CLI gate, then:

```bash
git add vscode/conversationClient.js \
  vscode/conversationParticipant.js \
  vscode/extension.js \
  vscode/package.json \
  vscode/src/test/suite/conversation.test.ts
git commit -m "feat: add Modelable VS Code chat participant"
```

---

### Task 6: Add Exact Diff, Apply, Discard, and Reset UX

**Files:**
- Create: `vscode/conversationPreview.js`
- Modify: `vscode/conversationParticipant.js`
- Modify: `vscode/conversationClient.js`
- Modify: `vscode/extension.js`
- Modify: `vscode/package.json`
- Modify: `vscode/src/test/suite/conversation.test.ts`

**Interfaces:**
- Consumes: Task 5 participant and client.
- Produces: exact virtual snapshots, View Diff command, structured anchors,
native Apply/Discard follow-ups, exact-ID lifecycle calls, and reset.

- [ ] **Step 1: Test exact snapshot storage**

Create tests:

```typescript
const store = new PreviewStore(fakeVscode);
const keys = store.put('session-1', 'change-1', [
  {
    uri: 'file:///workspace/customer.mdl',
    existedBefore: true,
    beforeText: 'before',
    afterText: 'after',
  },
]);

assert.strictEqual(store.provideTextDocumentContent(keys[0].beforeUri), 'before');
assert.strictEqual(store.provideTextDocumentContent(keys[0].afterUri), 'after');
store.deleteChangeSet('session-1', 'change-1');
assert.strictEqual(store.provideTextDocumentContent(keys[0].afterUri), undefined);
```

Add a new-file case whose before content is the empty string.

- [ ] **Step 2: Implement `PreviewStore` and View Diff**

Register the `modelable-preview` content provider. Key content by
session/change-set/file/side, URI-encode every component, and retain a sorted
file descriptor list.

`showDiff` opens the only file directly. For multiple files, call
`vscode.window.showQuickPick` with sorted relative paths. Invoke:

```javascript
await vscode.commands.executeCommand(
  'vscode.diff',
  selected.beforeUri,
  selected.afterUri,
  `${selected.label} — Modelable change ${changeSetId}`,
  { preview: true },
);
```

Add the public command contribution:

```json
{
  "command": "modelable.conversation.viewDiff",
  "title": "Modelable: View Conversation Diff"
}
```

Register it in `extension.js`:

```javascript
context.subscriptions.push(
  vscode.commands.registerCommand(
    'modelable.conversation.viewDiff',
    args => previewStore.showDiff(args.sessionId, args.changeSetId),
  ),
);
```

- [ ] **Step 3: Test structured rendering**

Use a fake stream and assert:

- canonical text is passed once to `markdown`;
- changed/affected refs with known file URIs call `anchor`;
- a preview with files calls `button` exactly once for View Diff;
- no source snapshot is included in command arguments; and
- answer/error replies do not register preview content.

- [ ] **Step 4: Render previews and references**

Cache `reply.previewFiles` before rendering the View Diff button:

```javascript
stream.button({
  command: 'modelable.conversation.viewDiff',
  title: 'View Diff',
  arguments: [{
    sessionId: reply.sessionId,
    changeSetId: reply.changeSetId,
  }],
});
```

Use `stream.anchor(vscode.Uri.parse(uri), ref)` only for locations supplied by
Python. Do not infer definition paths from ref strings in JavaScript.

- [ ] **Step 5: Test native follow-up actions**

Set `participant.followupProvider.provideFollowups` and assert a preview result
returns:

```javascript
[
  {
    prompt: '',
    label: 'Apply change set',
    participant: 'modelable-vscode.modelable',
    command: 'apply',
  },
  {
    prompt: '',
    label: 'Discard',
    participant: 'modelable-vscode.modelable',
    command: 'discard',
  },
]
```

Non-preview results return no apply/discard follow-ups.

- [ ] **Step 6: Route Apply and Discard with exact metadata**

For `request.command === "apply"` or `"discard"`:

1. recover the latest metadata;
2. require `sessionId`, `workspaceUri`, and `changeSetId`;
3. collect current dirty model URIs for apply;
4. call the matching client method;
5. render the returned canonical and structured result; and
6. delete cached preview documents only after a successful applied or
   discarded reply.

An old follow-up whose ID no longer matches must render the server's
fresh-preview error and retain the current cached preview.

- [ ] **Step 7: Implement Reset**

For `request.command === "reset"`, recover the session ID, send idempotent
close, delete all preview documents for that session, render
`"Reset the Modelable conversation session."`, and return result metadata
without a session ID so the next ordinary turn sets `createSession: true`.

- [ ] **Step 8: Run extension and CLI gates and commit**

Run all extension checks, the mandatory CLI gate, then:

```bash
git add vscode/conversationPreview.js \
  vscode/conversationParticipant.js \
  vscode/conversationClient.js \
  vscode/extension.js \
  vscode/package.json \
  vscode/src/test/suite/conversation.test.ts
git commit -m "feat: preview and apply VS Code conversation changes"
```

---

### Task 7: Harden Cancellation, Privacy, Compatibility, and End-to-End Coverage

**Files:**
- Modify: `vscode/conversationClient.js`
- Modify: `vscode/conversationParticipant.js`
- Modify: `vscode/conversationPreview.js`
- Modify: `vscode/src/test/suite/conversation.test.ts`
- Modify: `vscode/src/test/suite/lsp.test.ts`
- Modify: `cli/tests/test_lsp_conversation_service.py`
- Modify: `cli/tests/test_lsp_conversation_integration.py`

**Interfaces:**
- Consumes: complete Python and extension flows from Tasks 1–6.
- Produces: restart-safe, cancellation-safe, privacy-safe behavior and full
cross-process smoke coverage.

- [ ] **Step 1: Add cancellation tests**

Use a cancelled token and delayed fake request:

```typescript
const pending = handler(request, context, stream, tokenSource.token);
tokenSource.cancel();
await pending;

assert.deepStrictEqual(client.closedSessions, ['session-1']);
assert.strictEqual(previewStore.hasSession('session-1'), false);
```

Issue one subsequent turn and assert its wire payload has
`createSession: true`. Assert cancellation does not log the prompt or late
reply.

- [ ] **Step 2: Implement cancellation invalidation**

When a turn throws `vscode.CancellationError` or the token becomes cancelled:

1. send a best-effort close notification;
2. forget the local session ID;
3. delete its preview snapshots;
4. return no stale metadata; and
5. let the next turn generate a new UUID.

Do not expose apply as cancellable after the client sends the apply request.

- [ ] **Step 3: Add capability and restart tests**

Cover:

- absent capability;
- protocol version 2;
- recovered metadata followed by server session-expired error;
- language-client restart; and
- extension deactivation.

The first two produce an upgrade message without sending a custom request.
Expired/restarted sessions clear previews and explain that the user must repeat
the request.

- [ ] **Step 4: Add sanitized logging tests**

Inject an output channel and send distinctive prompt, diff, credential-like,
and diagnostic strings. Assert the output contains only request kind, protocol
version, elapsed time, reply kind, session lifecycle event, and sanitized error
code. Assert none of the distinctive sensitive strings occur.

- [ ] **Step 5: Add a real extension-host conversation smoke**

When `context.extensionMode === vscode.ExtensionMode.Test`, register
`modelable.test.conversationTurn`. Its handler calls
`conversationClient.turn({prompt}, {history: []}, token)` against the real
`LanguageClient` and returns the structured reply without rendering chat UI.
Do not contribute this command in `package.json`.

In `lsp.test.ts`, execute:

```typescript
const reply = await vscode.commands.executeCommand<{
  kind: string;
  protocolVersion: number;
  sessionId: string;
  focusedRef?: string;
}>(
  'modelable.test.conversationTurn',
  { prompt: 'is the workspace valid?' },
);
assert.ok(reply);
```

Then assert:

1. deterministic validation question returns `kind: "answer"`;
2. the result carries protocol version 1 and a session ID;
3. the active document produces `customer.CustomerFinancials@1` or the exact
   containing fixture ref; and
4. reset closes the server session.

Do not call an external model in extension-host tests.

- [ ] **Step 6: Complete Python boundary cases**

Add service and JSON-RPC tests for:

- 30-minute expiry boundary at exactly 1800 seconds and at 1800.001 seconds;
- deterministic least-recently-used eviction ordering;
- dirty file outside the selected root;
- active file nested below the workspace folder;
- no `workspace.mdl` effective-root fallback;
- malformed file URI;
- provider configuration failure; and
- idempotent close.

- [ ] **Step 7: Run all verification and commit**

Run the mandatory CLI gate and all four extension commands. Confirm the VSIX
contains `conversationClient.js`, `conversationParticipant.js`, and
`conversationPreview.js`. Then:

```bash
git add cli/tests/test_lsp_conversation_service.py \
  cli/tests/test_lsp_conversation_integration.py \
  vscode/conversationClient.js \
  vscode/conversationParticipant.js \
  vscode/conversationPreview.js \
  vscode/src/test/suite/conversation.test.ts \
  vscode/src/test/suite/lsp.test.ts
git commit -m "test: harden VS Code conversation lifecycle"
```

---

### Task 8: Document, Ship, and Archive the Completed Slice

Run this task only after Tasks 1–7 are complete and their implementation is
ready to merge.

**Files:**
- Modify: `vscode/README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/cli-reference.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`
- Move: `docs/superpowers/specs/2026-07-18-vscode-conversational-foundation-design.md` → `docs/superpowers/specs/archived/2026-07-18-vscode-conversational-foundation-design.md`
- Move: `docs/superpowers/plans/2026-07-18-vscode-conversational-foundation.md` → `docs/superpowers/plans/archived/2026-07-18-vscode-conversational-foundation.md`

**Interfaces:**
- Consumes: the shipped behavior and verification evidence from Tasks 1–7.
- Produces: user documentation, truthful shipped roadmap state, retained
native-model and operational follow-ups, and no completed active plan/spec.

- [ ] **Step 1: Document the user flow**

Add exact examples for:

```text
@modelable is the workspace valid?
@modelable add a customer entity with address
@modelable add a projection for active customers
```

Document saved-source requirements, active-editor workspace selection,
multi-root ambiguity, provider configuration, textual previews, View Diff,
Apply/Discard follow-ups, reset, expiry, restarts, and stale previews.

- [ ] **Step 2: Document the architecture boundary**

Add the implemented flow:

```text
VS Code ChatParticipant
  -> vscode-languageclient custom request v1
  -> bounded Python ConversationSession registry
  -> planner -> workspace editor -> compiler primitives
```

State that the extension does not parse, plan, validate, apply a
`WorkspaceEdit`, or write `.mdl` source.

- [ ] **Step 3: Update changelog and roadmap**

Mark the VS Code conversational foundation shipped. Keep the optional VS Code
Language Model API adapter as the next explicit provider follow-up, retaining
Python plan validation and editing. Keep operational actions after that with
authorization, preview, confirmation, and audit requirements.

- [ ] **Step 4: Archive the completed plan and spec**

Move both files into their `archived/` directories and repair links:

- archived spec → archived predecessor, root roadmap, archived plan;
- archived plan → archived spec;
- roadmap → archived spec.

Search the corpus to ensure no active-path links remain.

- [ ] **Step 5: Run documentation review and strict build**

Run all four phases from the `doc-review` skill, then:

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: PASS with no documentation-review warnings or blockers and no strict
MkDocs failure.

- [ ] **Step 6: Run full CLI and extension verification**

Run the mandatory CLI gate and:

```bash
cd ../vscode
npm ci
npm run check
npm run build
npm test
npm run package
```

Inspect the packaged VSIX file list and perform a manual Extension Development
Host smoke:

1. invoke `@modelable` with a grounded question;
2. preview a deterministic provider-backed entity addition;
3. open exact before/after diff;
4. discard without source changes;
5. preview again and apply;
6. observe the post-apply reply and file update; and
7. reset the session.

- [ ] **Step 7: Commit the closeout**

```bash
git add CHANGELOG.md ROADMAP.md docs vscode/README.md
git commit -m "docs: document VS Code conversational management"
```

## Final Verification

Before publishing the completed branch:

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short

cd ../vscode
npm ci
npm run check
npm run build
npm test
npm run package

cd ..
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
git diff --check main...HEAD
git status --short
```

Expected final state:

- every command exits zero;
- all implementation, protocol, extension-host, and existing tests pass;
- the VSIX packages all three conversation JavaScript modules;
- the worktree is clean;
- the roadmap retains the optional VS Code native-model adapter and later
  operational-management work; and
- the completed plan and spec exist only under their archived directories.
