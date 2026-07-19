# Conversational Compilation Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe local compilation to CLI and VS Code conversations through a shared service that stages exact output, explains affected definitions, requires explicit confirmation, rolls back failures, and records a private audit.

**Architecture:** Extract Click-independent compilation orchestration into `CompilationService`. Direct CLI compilation executes through the service immediately, while conversations retain a staged `PendingCompilation` and promote its exact bytes only after a freshness-bound `/apply`. Python owns planning, path policy, compilation, transactions, audit, and protocol data; VS Code only renders the structured reply and invokes lifecycle requests.

**Tech Stack:** Python 3.11+, dataclasses, Pydantic, Click, pytest/pytest-lsp, Modelable compiler and emitters, lsprotocol/pygls, CommonJS JavaScript, VS Code Extension API 1.125, TypeScript 7, Mocha.

## Global Constraints

- Implement [Conversational Compilation Management — Design](../specs/2026-07-19-conversational-compilation-management-design.md) exactly.
- Compilation is local-only; planner output cannot contain URLs, credentials, registry paths, commands, executables, environment variables, or arbitrary flags.
- Conversational output paths are workspace-relative, stay inside the resolved workspace, avoid `.git` and internal `.modelable` control paths, and never overlap `.mdl` sources.
- Preview must not create or modify any workspace file.
- Apply writes the exact staged bytes without recompiling.
- Text previews are complete and limited to 2 MiB total; larger previews fail safely.
- Binary previews expose purpose, path, status, size, and SHA-256 only.
- Output behavior remains non-destructive: never remove an unmentioned destination file.
- Only literal `/apply` or the native VS Code Apply action authorizes a pending compilation.
- One conversation session owns at most one pending source change or compilation.
- Every successful conversational apply writes `.modelable/audit/compilations/<action-id>.json`; direct CLI compilation does not.
- The protocol version becomes `2`; Python and the bundled extension fail clearly on version mismatch.
- Preserve existing source-edit conversation behavior, including its current apply aliases.
- Follow test-driven development: write and run each failing test before production changes.
- Before every commit, run all four required commands from `cli/`.

---

## File Structure

Create focused operational modules:

- `cli/src/modelable/operations/__init__.py`: public operational-service exports.
- `cli/src/modelable/operations/compilation.py`: request/result types, direct execution, staging lifecycle, path policy, and manifest construction.
- `cli/src/modelable/operations/file_transaction.py`: freshness checks, sibling temporary writes, backup, promotion, verification, and rollback.
- `cli/src/modelable/operations/compilation_audit.py`: versioned privacy-preserving compilation audit records.
- `cli/tests/test_compilation_service.py`: direct parity, staging, preview classification, paths, freshness, and lifecycle.
- `cli/tests/test_file_transaction.py`: deterministic promotion and injected rollback failures.
- `cli/tests/test_compilation_audit.py`: audit schema, privacy, and write failure behavior.

Keep existing responsibilities:

- `cli/src/modelable/commands/compile.py`: Click declarations and terminal rendering only.
- `cli/src/modelable/llm/conversation_plan.py`: closed planner schemas.
- `cli/src/modelable/llm/conversation_planner.py`: provider prompt and deterministic `/compile` parsing.
- `cli/src/modelable/llm/conversation.py`: one pending-action lifecycle and shared reply rendering.
- `cli/src/modelable/lsp/conversation_protocol.py`: protocol-v2 request/reply serialization.
- `cli/src/modelable/lsp/conversation_service.py`: saved/dirty document and session checks.
- `vscode/conversationClient.js`: protocol-v2 transport and dirty-document collection.
- `vscode/conversationPreview.js`: exact text preview virtual documents.
- `vscode/conversationParticipant.js`: Markdown, anchors, binary summaries, and Apply/Discard presentation.

---

### Task 1: Extract the Shared Compilation Service

**Files:**
- Create: `cli/src/modelable/operations/__init__.py`
- Create: `cli/src/modelable/operations/compilation.py`
- Create: `cli/tests/test_compilation_service.py`
- Modify: `cli/src/modelable/commands/compile.py`
- Modify: `cli/tests/test_cli.py`
- Modify: `cli/tests/test_cli_compile.py`
- Modify: `cli/tests/test_descriptor_artifacts.py`

**Interfaces:**
- Consumes: existing `load_workspace`, registry-ID allocation, registry build, `write_plans`, emitter functions, and descriptor helpers.
- Produces: `CompilationRequest`, `CompilationEvent`, `DirectCompilationResult`, and `CompilationService.execute_direct(request)`.

- [ ] **Step 1: Write failing service-parity tests**

```python
def test_execute_direct_writes_registry_plans_and_rust_artifacts(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    request = CompilationRequest(
        source=source,
        target="rust",
        out_dir=tmp_path / "generated",
        registry_path=str(tmp_path / ".modelable" / "registry.db"),
        registry_ids_path=tmp_path / "registry-ids.lock",
    )

    result = CompilationService().execute_direct(request)

    assert result.written_paths == tuple(sorted(result.written_paths))
    assert tmp_path / "registry-ids.lock" in result.written_paths
    assert tmp_path / ".modelable" / "registry.db" in result.written_paths
    assert any(path.is_relative_to(tmp_path / ".modelable" / "plans") for path in result.written_paths)
    assert any(path.suffix == ".rs" for path in result.written_paths)
```

Add separate tests for domain scoping, each implemented target's existing smoke
fixture, Protobuf descriptors, gRPC descriptors, warnings, empty output, an
orphaned ledger, and the existing OCI unsupported error.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
uv run pytest tests/test_compilation_service.py -v
```

Expected: collection fails because `modelable.operations.compilation` does not
exist.

- [ ] **Step 3: Define the service types**

```python
@dataclass(frozen=True)
class CompilationRequest:
    source: Path
    target: str
    out_dir: Path | None = None
    registry_path: str = ".modelable/registry.db"
    registry_ids_path: Path = Path("registry-ids.lock")
    allow_orphaned_registry_ids: bool = False
    domains: tuple[str, ...] = ()
    descriptor_set: bool = False


@dataclass(frozen=True)
class CompilationEvent:
    level: Literal["ok", "warning", "info"]
    message: str
    path: Path | None = None
    content_hash: str | None = None


@dataclass(frozen=True)
class DirectCompilationResult:
    written_paths: tuple[Path, ...]
    events: tuple[CompilationEvent, ...]
```

- [ ] **Step 4: Move orchestration behind `CompilationService`**

Implement:

```python
class CompilationService:
    def execute_direct(self, request: CompilationRequest) -> DirectCompilationResult:
        return _execute_compilation(request)
```

Move the existing command's domain validation, registry-ID allocation, local
registry build, plan generation, target dispatch, artifact serialization, and
descriptor generation into `_execute_compilation`. Preserve the existing order:
registry, plans, target artifacts. Replace `click.ClickException` inside the
service with `CompilationError`; translate it back to `click.ClickException` in
the command. Do not import Click or the shared Rich console from
`modelable.operations`.

The target dispatch must retain every current branch:

```python
TARGETS = (
    "json-schema", "markdown", "typescript", "csharp", "java", "python",
    "rust", "go", "dbt-yaml", "fhir-profile", "openmetadata",
    "openlineage", "odcs", "protobuf", "grpc", "sql-postgres",
    "sql-clickhouse",
)
```

- [ ] **Step 5: Make the Click command a thin adapter**

```python
try:
    result = CompilationService().execute_direct(
        CompilationRequest(
            source=source,
            target=target,
            out_dir=out_dir,
            registry_path=registry_path,
            registry_ids_path=registry_ids_path,
            allow_orphaned_registry_ids=allow_orphaned_registry_ids,
            domains=domains,
            descriptor_set=descriptor_set,
        )
    )
except CompilationError as error:
    raise click.ClickException(str(error)) from error

for event in result.events:
    render_compilation_event(event, console)
```

- [ ] **Step 6: Run focused parity tests**

Run:

```bash
uv run pytest tests/test_compilation_service.py tests/test_cli.py tests/test_cli_compile.py tests/test_descriptor_artifacts.py -v
```

Expected: PASS with unchanged CLI assertions.

- [ ] **Step 7: Run required pre-commit gates and commit**

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/operations src/modelable/commands/compile.py tests/test_compilation_service.py tests/test_cli.py tests/test_cli_compile.py tests/test_descriptor_artifacts.py
git commit -m "refactor: extract compilation service"
```

---

### Task 2: Stage Exact Compilation Previews

**Files:**
- Modify: `cli/src/modelable/operations/compilation.py`
- Modify: `cli/tests/test_compilation_service.py`

**Interfaces:**
- Consumes: `CompilationRequest` and Task 1's internal compilation runner.
- Produces: `CompilationPolicy`, `CompilationFilePreview`, `RegistryIdChange`, `PendingCompilation`, `CompilationService.preview()`, and `CompilationService.discard()`.

- [ ] **Step 1: Write failing no-write and classification tests**

```python
def test_preview_stages_exact_files_without_mutating_workspace(tmp_path: Path) -> None:
    source = write_workspace(tmp_path)
    before = snapshot_tree(tmp_path)

    pending = CompilationService(temp_root=tmp_path.parent).preview(
        CompilationRequest(source=source, target="json-schema"),
        policy=CompilationPolicy.conversation(),
    )

    assert snapshot_tree(tmp_path) == before
    assert {file.status for file in pending.files} >= {"created"}
    assert all(file.staged_path.is_relative_to(pending.staging_dir) for file in pending.files)
    assert pending.affected_definitions
```

Add tests for changed and unchanged text, binary registry/descriptor summaries,
new registry IDs, canonical ordering, complete text diffs, the 2 MiB limit,
unknown domains, path traversal, `.git`, internal `.modelable` paths, `.mdl`
overlap, and escaping symlinks.

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/test_compilation_service.py -k "preview or path or symlink" -v
```

Expected: FAIL because `preview` and preview models are absent.

- [ ] **Step 3: Add immutable preview models**

```python
@dataclass(frozen=True)
class CompilationPolicy:
    restrict_to_workspace: bool
    write_audit: bool

    @classmethod
    def conversation(cls) -> "CompilationPolicy":
        return cls(restrict_to_workspace=True, write_audit=True)


@dataclass(frozen=True)
class CompilationFilePreview:
    category: Literal["registry_ids", "registry", "plan", "artifact", "descriptor"]
    destination: Path
    staged_path: Path
    status: Literal["created", "changed", "unchanged"]
    media_type: str
    ref: str | None
    before_hash: str | None
    after_hash: str
    before_size: int
    after_size: int
    before_text: str | None
    after_text: str | None
    diff_text: str | None


@dataclass(frozen=True)
class RegistryIdChange:
    ref: str
    registry_id: int


@dataclass(frozen=True)
class PendingCompilation:
    action_id: str
    request: CompilationRequest
    workspace_root: Path
    staging_dir: Path
    files: tuple[CompilationFilePreview, ...]
    source_fingerprints: tuple[FileFingerprint, ...]
    affected_definitions: tuple[AffectedDefinition, ...]
    registry_id_changes: tuple[RegistryIdChange, ...]
    warnings: tuple[str, ...]
    manifest_fingerprint: str
```

- [ ] **Step 4: Implement isolated staging**

`preview()` must create an OS-private temporary directory, rebase registry,
plan, descriptor, and artifact destinations into it, invoke the real Task 1
runner, compare staged bytes with destinations, calculate full UTF-8 diffs,
classify binary content, calculate hashes/sizes, and reject text payloads above
`2 * 1024 * 1024`.

Use the caller-supplied ID factory for deterministic tests:

```python
class CompilationService:
    def __init__(
        self,
        *,
        temp_root: Path | None = None,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self.temp_root = temp_root
        self.new_id = new_id
```

- [ ] **Step 5: Implement conversation path policy**

Normalize and resolve every path, reject prohibited ancestors and source
overlap, and record resolved parent fingerprints. The policy must reject
`oci://` before staging and allow descriptor sets only for `protobuf` and
`grpc`.

- [ ] **Step 6: Implement discard and cleanup**

```python
def discard(self, pending: PendingCompilation) -> None:
    shutil.rmtree(pending.staging_dir)
```

Make repeated discard safe, but surface a cleanup error when the directory
still exists after removal.

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest tests/test_compilation_service.py -v
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/operations/compilation.py tests/test_compilation_service.py
git commit -m "feat: stage compilation previews"
```

---

### Task 3: Add Freshness, Rollback, and Audit

**Files:**
- Create: `cli/src/modelable/operations/file_transaction.py`
- Create: `cli/src/modelable/operations/compilation_audit.py`
- Create: `cli/tests/test_file_transaction.py`
- Create: `cli/tests/test_compilation_audit.py`
- Modify: `cli/src/modelable/operations/compilation.py`
- Modify: `cli/tests/test_compilation_service.py`

**Interfaces:**
- Consumes: `CompilationRequest` and `PendingCompilation`.
- Produces: `CompilationConfirmation`, `AppliedCompilation`, `FileTransaction.promote()`, `CompilationAuditRecord`, transactional `CompilationService.execute_direct()`, and `CompilationService.apply()`.

- [ ] **Step 1: Write failing transaction tests**

```python
@pytest.mark.parametrize("fail_after", [0, 1, 2])
def test_transaction_restores_every_file_after_injected_failure(
    tmp_path: Path, fail_after: int
) -> None:
    destinations = seed_destinations(tmp_path)
    before = snapshot_tree(tmp_path)
    transaction = FileTransaction(replace=FailingReplace(fail_after))

    with pytest.raises(FileTransactionError):
        transaction.promote(staged_files(destinations))

    assert snapshot_tree(tmp_path) == before
```

Also test created-file removal, empty-directory cleanup, lock contention,
post-write hash verification, and individually reported rollback errors.

- [ ] **Step 2: Write failing apply/audit tests**

```python
def test_apply_writes_exact_stage_and_private_audit(tmp_path: Path) -> None:
    service, pending = preview_rust(tmp_path)
    staged = {item.destination: item.staged_path.read_bytes() for item in pending.files}

    applied = service.apply(
        pending,
        confirmation=CompilationConfirmation(
            session_id="session-1",
            action_id=pending.action_id,
            manifest_fingerprint=pending.manifest_fingerprint,
            surface="cli-chat",
            provider="ollama",
            model="qwen",
        ),
    )

    assert {path: path.read_bytes() for path in staged} == staged
    audit = json.loads(applied.audit_path.read_text(encoding="utf-8"))
    assert audit["manifestFingerprint"] == pending.manifest_fingerprint
    assert "prompt" not in json.dumps(audit).lower()
```

Add stale source, destination, ledger, registry, parent-symlink, foreign ID,
manifest tampering, audit-write failure, and no-recompile tests. Add a direct
execution failure-injection test proving that a target emitter or promotion
failure leaves the trusted CLI destinations byte-for-byte unchanged. Direct
execution must retain its existing accepted path forms and must not write a
conversational audit.

- [ ] **Step 3: Implement the file transaction**

```python
class FileTransaction:
    def promote(self, files: Sequence[StagedFile]) -> tuple[Path, ...]:
        self._acquire_lock()
        backups = self._backup_existing(files)
        created: list[Path] = []
        try:
            self._write_sibling_temporaries(files)
            self._replace_destinations(files, created)
            self._verify_hashes(files)
            return tuple(sorted(file.destination for file in files))
        except Exception as error:
            rollback_errors = self._rollback(backups, created)
            raise FileTransactionError(error, rollback_errors) from error
        finally:
            self._release_lock()
```

Use sibling temporary files plus `os.replace`; never delete an unmentioned
destination.

- [ ] **Step 4: Define audit and apply models**

```python
@dataclass(frozen=True)
class CompilationConfirmation:
    session_id: str
    action_id: str
    manifest_fingerprint: str
    surface: Literal["cli-chat", "vscode-chat"]
    provider: str | None
    model: str | None


@dataclass(frozen=True)
class AppliedCompilation:
    action_id: str
    written_paths: tuple[Path, ...]
    affected_definitions: tuple[AffectedDefinition, ...]
    files: tuple[CompilationFilePreview, ...]
    audit_path: Path
```

`CompilationAuditRecord` uses `schemaVersion: 1` and the exact privacy fields
from the design. Serialize with sorted keys and a trailing newline.

- [ ] **Step 5: Implement freshness-bound apply**

Recompute source, destination, registry, ledger, parent-path, staged-file, and
manifest hashes. Reject on the first deterministic mismatch with
`StaleCompilationError`. Add the staged audit record as the final
`FileTransaction` member so audit failure rolls back every compilation file.

- [ ] **Step 6: Make direct compilation transactional**

Change `execute_direct()` to generate ledger, registry, plans, artifacts, and
descriptors in an isolated temporary directory, then promote the complete
destination set with `FileTransaction`. It does not perform conversational
freshness confirmation, enforce conversational path policy, or write an audit
record. Preserve the existing direct CLI paths, output bytes, console events,
and errors. Always clean its staging directory on success or failure.

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest tests/test_file_transaction.py tests/test_compilation_audit.py tests/test_compilation_service.py -v
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/operations tests/test_file_transaction.py tests/test_compilation_audit.py tests/test_compilation_service.py
git commit -m "feat: apply audited compilation transactions"
```

---

### Task 4: Add Typed Compile Planning

**Files:**
- Modify: `cli/src/modelable/llm/conversation_plan.py`
- Modify: `cli/src/modelable/llm/conversation_planner.py`
- Modify: `cli/tests/test_conversation_plan.py`

**Interfaces:**
- Consumes: implemented target names.
- Produces: `CompilePlan` and deterministic `parse_compile_command(message)`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_compile_plan_is_closed_and_schema_validated() -> None:
    plan = parse_conversation_plan(
        '{"kind":"compile","target":"rust","domains":["customer"],'
        '"output":null,"descriptor_set":false,"summary":"Compile customer."}'
    )
    assert isinstance(plan, CompilePlan)
    assert plan.target == "rust"


@pytest.mark.parametrize("field", ["url", "token", "registry", "command", "environment"])
def test_compile_plan_rejects_operational_escape_hatches(field: str) -> None:
    payload = valid_compile_payload() | {field: "forbidden"}
    with pytest.raises(ValidationError):
        parse_conversation_plan(json.dumps(payload))
```

Add descriptor/target compatibility and relative-output validation cases.

- [ ] **Step 2: Run and verify RED**

```bash
uv run pytest tests/test_conversation_plan.py -k compile -v
```

Expected: FAIL because `CompilePlan` is absent and compile remains unsupported.

- [ ] **Step 3: Add `CompilePlan`**

```python
class CompilePlan(StrictPlanModel):
    kind: Literal["compile"] = "compile"
    target: ImplementedTarget
    domains: list[str] = Field(default_factory=list)
    output: str | None = None
    descriptor_set: bool = False
    summary: str
```

Add a model validator for descriptor targets and normalized relative output.
Include `CompilePlan` in `ConversationPlan`; keep remote operations represented
by `UnsupportedPlan(roadmap_area="operations")`.

- [ ] **Step 4: Add deterministic `/compile` parsing**

Use `shlex.split` only as an argument tokenizer; never execute the result.
Accept the exact syntax in the design and produce `CompilePlan`. Reject unknown
options and missing values with a `ClarificationPlan`.

- [ ] **Step 5: Update the provider instruction**

Tell the provider to choose `kind: "compile"` only for local generation and to
return `UnsupportedPlan` for publish, sync, URL, credential, shell, or remote
requests. Add examples for Rust, domain-scoped JSON Schema, and Protobuf
descriptors.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/test_conversation_plan.py -v
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/llm/conversation_plan.py src/modelable/llm/conversation_planner.py tests/test_conversation_plan.py
git commit -m "feat: plan local compilation requests"
```

---

### Task 5: Integrate Compilation into Conversations and CLI Chat

**Files:**
- Modify: `cli/src/modelable/llm/conversation.py`
- Modify: `cli/src/modelable/llm/chat.py`
- Modify: `cli/src/modelable/commands/llm.py`
- Modify: `cli/tests/test_conversation.py`
- Modify: `cli/tests/test_llm_provider_integration.py`

**Interfaces:**
- Consumes: `CompilePlan`, `CompilationService`, `PendingCompilation`, and `AppliedCompilation`.
- Produces: compilation preview/applied `ConversationReply` data and strict `/apply` lifecycle.

- [ ] **Step 1: Write failing end-to-end conversation tests**

```python
def test_compile_conversation_previews_then_applies_exact_stage(tmp_path: Path) -> None:
    write_workspace(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(compile_plan("rust")),
        compilation_service=CompilationService(new_id=lambda: "compile-1"),
    )

    preview = session.turn("compile this workspace to Rust")
    assert preview.kind == "preview"
    assert preview.operation_kind == "compile"
    assert preview.change_set_id == "compile-1"
    assert not (tmp_path / "dist" / "rust").exists()

    applied = session.turn("/apply")
    assert applied.kind == "applied"
    assert applied.audit_path is not None
```

Add tests proving `apply`, `apply it`, and `confirm` do not apply a compilation;
source changes retain those aliases; replacement/discard/expiry cleanup staging;
large preview errors do not become pending; and the provider cannot authorize.

- [ ] **Step 2: Run and verify RED**

```bash
uv run pytest tests/test_conversation.py -k compil -v
```

- [ ] **Step 3: Generalize pending actions**

```python
type PendingAction = PendingChangeSet | PendingCompilation


@dataclass(frozen=True)
class ConversationReply:
    kind: ReplyKind
    text: str
    change_set_id: str | None = None
    operation_kind: Literal["source_change", "compile"] | None = None
    compilation_files: tuple[CompilationFilePreview, ...] = ()
    registry_id_changes: tuple[RegistryIdChange, ...] = ()
    audit_path: Path | None = None
```

Inject `CompilationService` and provider/model identity into
`ConversationSession`. Route `CompilePlan` to `_preview_compilation`.

- [ ] **Step 4: Enforce compilation confirmation**

When the pending action is `PendingCompilation`, only exact `/apply` calls
`CompilationService.apply`. Source-change pending actions keep current aliases.
`/discard`, replacement, close, and expiry call the correct cleanup path.

- [ ] **Step 5: Render the shared textual preview**

Render normalized plan, affected definitions, created/changed/unchanged files,
registry-ID additions, complete text diffs, binary sizes/hashes, warnings, and
literal `/apply`/`/discard` guidance. Applied replies list paths, hashes, and
audit path.

- [ ] **Step 6: Update CLI help and lifecycle**

Document `/compile` in chat help. Ensure EOF, `/quit`, and exceptions close the
session and remove staging.

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest tests/test_conversation.py tests/test_llm_provider_integration.py -v
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/llm/conversation.py src/modelable/llm/chat.py src/modelable/commands/llm.py tests/test_conversation.py tests/test_llm_provider_integration.py
git commit -m "feat: manage compilation through chat"
```

---

### Task 6: Extend the Language-Server Protocol

**Files:**
- Modify: `cli/src/modelable/lsp/conversation_protocol.py`
- Modify: `cli/src/modelable/lsp/conversation_service.py`
- Modify: `cli/tests/test_lsp_conversation_protocol.py`
- Modify: `cli/tests/test_lsp_conversation_service.py`
- Modify: `cli/tests/test_lsp_conversation_integration.py`

**Interfaces:**
- Consumes: compilation `ConversationReply`.
- Produces: protocol-v2 structured compilation files, registry changes, audit URI, and dirty-destination enforcement.

- [ ] **Step 1: Write failing protocol-v2 tests**

```python
def test_serialize_compile_preview_protocol_v2() -> None:
    payload = serialize_conversation_reply(
        compile_preview_reply(),
        session_id="session-1",
        workspace_uri=WORKSPACE_URI,
    )
    assert payload["protocolVersion"] == 2
    assert payload["operationKind"] == "compile"
    assert payload["compilationFiles"][0]["status"] == "changed"
    assert payload["registryIdChanges"] == [{"ref": "customer.SchemaId", "registryId": 1}]
```

Add exact field tests for text snapshots, binary hashes/sizes, audit URI, and
the retained `changeSetId`.

- [ ] **Step 2: Write dirty-destination tests**

Pass a dirty generated-file URI in `ConversationChangeSetParams` and assert
apply fails with exact save guidance; a dirty unrelated file must not block.

- [ ] **Step 3: Bump and serialize protocol v2**

Set `PROTOCOL_VERSION = 2`. Add stable camelCase fields:

```python
{
    "operationKind": reply.operation_kind,
    "compilationFiles": [_serialize_compilation_file(item) for item in reply.compilation_files],
    "registryIdChanges": [
        {"ref": item.ref, "registryId": item.registry_id}
        for item in reply.registry_id_changes
    ],
    "auditUri": reply.audit_path.resolve().as_uri() if reply.audit_path else None,
}
```

- [ ] **Step 4: Enforce dirty destinations in the service**

Retain the existing saved-`.mdl` preview guard. During apply, resolve every
dirty URI and reject only those matching pending compilation destinations.
Keep source-change behavior unchanged.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/test_lsp_conversation_protocol.py tests/test_lsp_conversation_service.py tests/test_lsp_conversation_integration.py -v
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/lsp/conversation_protocol.py src/modelable/lsp/conversation_service.py tests/test_lsp_conversation_protocol.py tests/test_lsp_conversation_service.py tests/test_lsp_conversation_integration.py
git commit -m "feat: expose compilation conversation protocol"
```

---

### Task 7: Render Compilation in VS Code

**Files:**
- Modify: `vscode/conversationClient.js`
- Modify: `vscode/conversationPreview.js`
- Modify: `vscode/conversationParticipant.js`
- Modify: `vscode/src/test/suite/conversation.test.ts`
- Modify: `vscode/src/test/suite/lsp.test.ts`

**Interfaces:**
- Consumes: protocol-v2 compilation reply.
- Produces: text diff selection, binary summaries, definition anchors, exact Apply/Discard actions, and all-destination dirty URI reporting.

- [ ] **Step 1: Write failing extension tests**

```typescript
test('compile preview stores text diffs and renders binary hashes', () => {
  const reply = compilePreviewReply();
  renderReply(reply, stream, vscodeApi, previewStore);

  assert.deepStrictEqual(stream.buttons, [{
    command: 'modelable.conversation.viewDiff',
    title: 'View generated diffs',
    arguments: [{ sessionId: 'session-1', changeSetId: 'compile-1' }],
  }]);
  assert.match(stream.markdownText, /registry\.db.*SHA-256/);
});
```

Add tests for protocol version 2, affected-definition anchors, created text
files, multiple diff selection, Apply compilation labeling, audit links, and a
dirty generated file included in apply payload.

- [ ] **Step 2: Run and verify RED**

```bash
npm run check
npm test -- --grep "compile preview"
```

Expected: FAIL on protocol version and missing compilation rendering.

- [ ] **Step 3: Update transport and dirty-document collection**

Set `PROTOCOL_VERSION = 2`. Change `collectDirtyDocumentUris` to include every
dirty file-scheme document inside the selected workspace, not only `mdl`.
Python remains responsible for deciding whether a dirty URI intersects the
pending action.

- [ ] **Step 4: Extend preview storage**

Feed text entries from `compilationFiles` into `PreviewStore` using their exact
before/after snapshots. Preserve source-change previews. Use generated-file
suffixes in virtual URIs instead of forcing `.mdl`.

- [ ] **Step 5: Render operational details**

Render the shared `reply.text`, anchors, binary summaries, registry-ID changes,
and audit URI. Use button title `View generated diffs` for compilation and
`View Diff` for source changes. Follow-up label is `Apply compilation` when
`operationKind === "compile"`.

- [ ] **Step 6: Run extension and real-LSP tests**

```bash
npm run check
npm run build
npm test
npm run package
```

Expected: all extension unit, integration, and package checks pass.

- [ ] **Step 7: Run required repository gates and commit**

From `cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Then:

```bash
git add vscode/conversationClient.js vscode/conversationPreview.js vscode/conversationParticipant.js vscode/src/test/suite/conversation.test.ts vscode/src/test/suite/lsp.test.ts
git commit -m "feat: preview compilation in VS Code"
```

---

### Task 8: Complete Documentation, Acceptance, and Archive Bookkeeping

**Files:**
- Modify: `docs/cli-reference.md`
- Modify: `docs/architecture.md`
- Modify: `docs/maintainers.md`
- Modify: `vscode/README.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`
- Move: `docs/superpowers/specs/2026-07-19-conversational-compilation-management-design.md` → `docs/superpowers/specs/archived/2026-07-19-conversational-compilation-management-design.md`
- Move: `docs/superpowers/plans/2026-07-19-conversational-compilation-management.md` → `docs/superpowers/plans/archived/2026-07-19-conversational-compilation-management.md`
- Modify: documentation links affected by the moves.

**Interfaces:**
- Consumes: the complete shipped behavior from Tasks 1–7.
- Produces: truthful user, maintainer, roadmap, changelog, and archived planning state.

- [ ] **Step 1: Write failing documentation contract tests**

In the existing CLI/help and release-workflow test modules, assert:

```python
assert "/compile" in chat_help
assert "literal /apply" in cli_reference
assert ".modelable/audit/compilations/" in cli_reference
assert "Conversational Compilation Management" in roadmap
assert "specs/archived/2026-07-19-conversational-compilation-management-design.md" in roadmap
```

- [ ] **Step 2: Run documentation contract tests and verify RED**

```bash
uv run pytest tests/test_conversation.py tests/test_release_workflow.py -k "help or roadmap or documentation" -v
```

- [ ] **Step 3: Update user and maintainer documentation**

Document exact `/compile` syntax, natural-language examples, target/domain/output
rules, descriptor behavior, preview fields, strict `/apply`, discard/staleness,
dirty generated files, rollback, audit privacy, staging cleanup, and direct CLI
fallback for previews above 2 MiB.

- [ ] **Step 4: Update roadmap and archive plans**

Mark only local conversational compilation shipped. Keep registry sync,
publishing, external services, WebLLM, and the VS Code native-model adapter
unshipped. Move both active files with `git mv` and repair relative links.

- [ ] **Step 5: Run strict documentation review**

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Run all four doc-review phases. Expected: PASS with no placeholders, broken
links, roadmap contradictions, or missing archive moves.

- [ ] **Step 6: Run complete acceptance flow**

Use a fake provider to execute:

```text
compile this workspace to Rust
/apply
```

Verify the preview contains affected definitions and exact file evidence,
workspace bytes remain unchanged before `/apply`, applied bytes match staging,
the audit excludes prompts/content, and a changed destination makes a second
apply stale.

- [ ] **Step 7: Run every final gate**

From `cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

From `vscode/`:

```bash
npm run check
npm run build
npm test
npm run package
```

From the repository root:

```bash
uv run python .github/scripts/run_browser_playground.py --skip-install
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
git diff --check
```

- [ ] **Step 8: Commit the shipped documentation and archives**

```bash
git add CHANGELOG.md ROADMAP.md docs vscode/README.md cli/tests
git commit -m "docs: ship conversational compilation management"
```

---

## Final Review Checklist

- [ ] Direct `modelable compile` retains targets, options, success bytes, console results, and user-facing errors.
- [ ] Failed direct compilation no longer leaves partial local state.
- [ ] Conversational preview performs the real compile without workspace writes.
- [ ] Text diffs are complete and binary changes use exact hashes/sizes.
- [ ] Affected domains, entities, projections, semantic types, and registry-ID changes are explained.
- [ ] The planner cannot select remote services, credentials, commands, registry paths, or unsafe outputs.
- [ ] Only literal `/apply` or native Apply confirms compilation.
- [ ] Apply verifies freshness and promotes staged bytes without recompiling.
- [ ] Injected failures prove complete rollback.
- [ ] Successful conversational applies write privacy-preserving audit schema v1.
- [ ] Source-edit conversations remain compatible.
- [ ] Protocol v2 and the bundled VS Code extension agree.
- [ ] Registry sync, publishing, external services, WebLLM, and native VS Code models remain deferred.
- [ ] The completed spec and plan are archived in the implementation PR.
