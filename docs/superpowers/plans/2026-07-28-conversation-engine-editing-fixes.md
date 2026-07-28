# Conversation Engine Editing Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the shared LLM conversation/editing engine (used by CLI chat, VS Code, the web playground, and `modelable llm update`) so edit requests either succeed or fail with a reason the user understands, instead of silently no-oping, throwing confusing internal errors, or behaving differently across surfaces.

**Architecture:** All fixes live in `cli/src/modelable/llm/` (the shared conversation engine) and `cli/src/modelable/lsp/conversation_service.py` (the VS Code LSP entry point). No `web/src` or VS Code JS changes are in scope. The core mechanism for the versioning fix is a `session_editable_refs` set that `ConversationEngine` accumulates from applied change sets and forwards into `WorkspaceEditor`, so a ref created earlier in the same conversation stays editable without a version bump.

**Tech Stack:** Python 3.14, pydantic (typed plans), pytest.

## Global Constraints

- Run `ruff format` and `ruff check` on every touched file before committing (per project convention).
- Every new/changed public behavior needs a test; no task is done until its tests pass.
- Do not modify `web/src/*` or VS Code `.js` files — those are out of scope (see the approved design's non-goals).
- Preserve existing public function signatures wherever a caller outside this plan's files depends on them (e.g. `update_definition()`'s signature and `UpdateResult` shape, used by `cli/src/modelable/commands/llm.py`).

---

### Task 1: `WorkspaceEditor` accepts session-scoped editable refs

**Files:**
- Modify: `cli/src/modelable/llm/workspace_editor.py:153` (`preview`), `:457` (`apply`)
- Test: `cli/tests/test_workspace_editor.py`

**Interfaces:**
- Produces: `WorkspaceEditor.preview(self, plan: ChangeSetPlan, *, session_editable_refs: frozenset[str] = frozenset()) -> PendingChangeSet` and `WorkspaceEditor.apply(self, pending: PendingChangeSet, *, session_editable_refs: frozenset[str] = frozenset()) -> AppliedChangeSet`. Later tasks pass a non-empty `session_editable_refs` to let a ref created by an earlier, already-applied turn in the same conversation stay editable without a version bump or `edit_mode="draft"`.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_workspace_editor.py` (near `test_existing_model_version_requires_explicit_draft_mode_and_warns` at line 507, which this mirrors):

```python
def test_session_editable_refs_allow_field_edit_without_draft_mode_or_new_version(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    original = """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".lstrip()
    source.write_text(original, encoding="utf-8")
    operation = AddField(
        target="customer.Customer@1",
        field=FieldSpec(name="email", type=PrimitiveType(kind="string"), optional=True),
    )

    pending = WorkspaceEditor(tmp_path).preview(
        ChangeSetPlan(summary="Add email", operations=[operation]),
        session_editable_refs=frozenset({"customer.Customer@1"}),
    )

    assert "email?: string" in pending.candidate_sources[source]

    applied = WorkspaceEditor(tmp_path).apply(
        pending,
        session_editable_refs=frozenset({"customer.Customer@1"}),
    )
    assert "email?: string" in source.read_text(encoding="utf-8")
    assert applied.change_set_id == pending.change_set_id


def test_session_editable_refs_do_not_bypass_the_guard_for_untouched_refs(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    operation = AddField(
        target="customer.Customer@1",
        field=FieldSpec(name="email", type=PrimitiveType(kind="string"), optional=True),
    )

    with pytest.raises(WorkspaceEditError, match="append a new version or use draft mode"):
        WorkspaceEditor(tmp_path).preview(
            ChangeSetPlan(summary="Add email", operations=[operation]),
            session_editable_refs=frozenset({"customer.Customer@99"}),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_workspace_editor.py -k session_editable_refs -v`
Expected: FAIL with `TypeError: preview() got an unexpected keyword argument 'session_editable_refs'`

- [ ] **Step 3: Implement**

In `cli/src/modelable/llm/workspace_editor.py`, change the `preview` signature and its `editable_refs` initialization (currently line 153-159):

```python
    def preview(self, plan: ChangeSetPlan, *, session_editable_refs: frozenset[str] = frozenset()) -> PendingChangeSet:
        documents = self._copy_documents()
        changed_paths: set[Path] = set()
        changed: list[ChangedDefinition] = []
        affected: list[AffectedDefinition] = []
        appended_models: dict[str, str] = {}
        editable_refs: set[str] = set(session_editable_refs)
        renamed_refs: dict[str, str] = {}
```

Change the `apply` signature (currently line 457) and its internal restaging call (currently line 461):

```python
    def apply(
        self,
        pending: PendingChangeSet,
        *,
        session_editable_refs: frozenset[str] = frozenset(),
    ) -> AppliedChangeSet:
        if self._current_source_fingerprints() != pending.source_fingerprints:
            raise StaleChangeSetError("Workspace sources changed after this change set was previewed")

        restaged = self.preview(pending.plan, session_editable_refs=session_editable_refs)
        if restaged != pending:
            raise StaleChangeSetError("Change set no longer matches its deterministic preview")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_workspace_editor.py -k session_editable_refs -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full workspace_editor test suite to check for regressions**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_workspace_editor.py -v`
Expected: all PASS (the new keyword-only parameter has a default, so every existing call site and test is unaffected)

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/llm/workspace_editor.py cli/tests/test_workspace_editor.py
git commit -m "feat(llm): let WorkspaceEditor accept session-scoped editable refs"
```

---

### Task 2: Thread `session_editable_refs` through the backend protocol

**Files:**
- Modify: `cli/src/modelable/llm/conversation_backend.py:66-70` (Protocol)
- Modify: `cli/src/modelable/llm/filesystem_conversation.py:28-116, 212-251, 388-390`
- Modify: `cli/src/modelable/browser/conversation.py:71-129`
- Test: `cli/tests/test_conversation.py`, `cli/tests/test_browser_conversation.py`

**Interfaces:**
- Consumes: `WorkspaceEditor.preview(plan, *, session_editable_refs=...)` / `.apply(pending, *, session_editable_refs=...)` from Task 1.
- Produces: `ConversationBackend.preview_source_change(self, plan, replaced_action_id, *, session_editable_refs: frozenset[str] = frozenset()) -> ConversationReply`. Task 3 (`ConversationEngine`) will call this with the accumulated session refs on every turn.

- [ ] **Step 1: Write the failing test for the filesystem backend**

Add to `cli/tests/test_conversation.py` (find an existing test constructing a `FilesystemConversationBackend` directly to match its setup style; if none exists, construct one the same way `ConversationSession.__init__` does):

```python
def test_filesystem_backend_preview_accepts_session_editable_refs(tmp_path) -> None:
    from modelable.llm.filesystem_conversation import FilesystemConversationBackend
    from modelable.llm.conversation_plan import AddField, ChangeSetPlan, FieldSpec
    from modelable.parser.ir import PrimitiveType

    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    backend = FilesystemConversationBackend(path=tmp_path, session_id="s1")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation.py -k session_editable_refs -v`
Expected: FAIL with `TypeError: preview_source_change() got an unexpected keyword argument 'session_editable_refs'`

- [ ] **Step 3: Implement — protocol**

In `cli/src/modelable/llm/conversation_backend.py`, change the `preview_source_change` protocol method (currently lines 66-70):

```python
    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
        *,
        session_editable_refs: frozenset[str] = frozenset(),
    ) -> ConversationReply: ...
```

- [ ] **Step 4: Implement — filesystem backend**

In `cli/src/modelable/llm/filesystem_conversation.py`, add an instance attribute in `__init__` (after `self.editor: WorkspaceEditor | None = None` at line 48):

```python
        self.editor: WorkspaceEditor | None = None
        self._pending_session_editable_refs: frozenset[str] = frozenset()
```

Change `preview_source_change` (currently lines 87-106) to accept and use the new parameter:

```python
    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
        *,
        session_editable_refs: frozenset[str] = frozenset(),
    ) -> ConversationReply:
        from modelable.llm.conversation import (
            _render_cleanup_failure,
            render_pending_change_set,
        )

        replaced = self._pending
        actual_replaced_id = _pending_id(replaced)
        if replaced_action_id != actual_replaced_id:
            raise ValueError(
                f"Replaced action ID {replaced_action_id!r} does not match backend action {actual_replaced_id!r}"
            )
        try:
            if self.editor is None:
                self.editor = WorkspaceEditor(self.path, workspace=self.workspace)
            pending = self.editor.preview(plan, session_editable_refs=session_editable_refs)
        except WorkspaceEditError as error:
            return ConversationReply(kind="error", text=f"Could not preview workspace changes: {error}")
        self._pending_session_editable_refs = session_editable_refs
```

(Leave everything after that line in the method unchanged — it already continues with `cleanup_errors = self._dispose_actions(...)`.)

Change `apply` (currently lines 212-251) at the line that calls `self.editor.apply`:

```python
        try:
            applied = self.editor.apply(self._pending, session_editable_refs=self._pending_session_editable_refs)
        except WorkspaceEditError as error:
```

- [ ] **Step 5: Implement — browser backend**

In `cli/src/modelable/browser/conversation.py`, change `preview_source_change` (currently lines 96-100 and the `.preview(plan)` call at line 103):

```python
    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
        *,
        session_editable_refs: frozenset[str] = frozenset(),
    ) -> ConversationReply:
        self._assert_replaced(replaced_action_id)
        try:
            pending = WorkspaceEditor(Path("."), workspace=self._workspace).preview(
                plan, session_editable_refs=session_editable_refs
            )
        except WorkspaceEditError as error:
            return ConversationReply(kind="error", text=f"Could not preview workspace changes: {error}")
```

(`BrowserConversationBackend.apply` does not call `WorkspaceEditor.apply` — it applies `pending.candidate_sources` directly — so it needs no change.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation.py tests/test_browser_conversation.py tests/test_workspace_editor.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add cli/src/modelable/llm/conversation_backend.py cli/src/modelable/llm/filesystem_conversation.py cli/src/modelable/browser/conversation.py cli/tests/test_conversation.py
git commit -m "feat(llm): thread session_editable_refs through both conversation backends"
```

---

### Task 3: `ConversationEngine` tracks editable refs across turns

**Files:**
- Modify: `cli/src/modelable/llm/conversation_engine.py:42-233`
- Test: `cli/tests/test_conversation_engine.py`

**Interfaces:**
- Consumes: `ConversationBackend.preview_source_change(plan, replaced_action_id, *, session_editable_refs=...)` from Task 2.
- Produces: `ConversationEngine` now accepts turns that edit a ref it previously created/applied in the same session without requiring a version bump or `edit_mode="draft"`. No public signature changes to `ConversationEngine` itself — this is internal state.

- [ ] **Step 1: Write the failing test**

The existing `RecordingBackend` fake in `cli/tests/test_conversation_engine.py` (line 44) doesn't accept `session_editable_refs` yet, so update it first, then add the new test.

Change `RecordingBackend.preview_source_change` (currently lines 59-73):

```python
    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
        *,
        session_editable_refs: frozenset[str] = frozenset(),
    ) -> ConversationReply:
        self.previewed_plans.append(plan)
        self.previewed_session_editable_refs.append(session_editable_refs)
        action_id = f"change-{self.next_action}"
        self.next_action += 1
        return ConversationReply(
            kind="preview",
            text=f"preview:{action_id}:replaced:{replaced_action_id}",
            change_set_id=action_id,
            operation_kind="source_change",
            focused_ref="customer.Customer@1",
            changed=(ChangedDefinition(ref="customer.Customer@1", reason="created"),),
        )
```

Add a new field to the `RecordingBackend` dataclass (currently lines 43-50):

```python
@dataclass
class RecordingBackend:
    previewed_plans: list[ChangeSetPlan] = field(default_factory=list)
    previewed_session_editable_refs: list[frozenset[str]] = field(default_factory=list)
    applied_ids: list[str] = field(default_factory=list)
    discarded_ids: list[str] = field(default_factory=list)
    reset_calls: int = 0
    next_action: int = 1
    execute_query_called: bool = False
```

Add the import for `ChangedDefinition` at the top of the file:

```python
from modelable.llm.workspace_editor import ChangedDefinition
```

Add the new test:

```python
def test_engine_lets_second_turn_edit_a_ref_applied_earlier_in_the_session() -> None:
    engine, backend = engine_with_request_ids("request-1", "request-2")

    pending = engine.begin_turn("Create a customer")
    assert isinstance(pending, PendingPlanRequest)
    preview_reply = engine.resume_turn(pending.request_id, json.dumps(valid_create_customer_plan()))
    assert preview_reply.kind == "preview"
    applied_reply = engine.apply(preview_reply.change_set_id)
    assert applied_reply.kind == "applied"

    pending_2 = engine.begin_turn("Rename customerId to id")
    assert isinstance(pending_2, PendingPlanRequest)
    engine.resume_turn(pending_2.request_id, json.dumps(valid_create_customer_plan()))

    assert backend.previewed_session_editable_refs[-1] == frozenset({"customer.Customer@1"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_engine.py -k session_in_the_session -v`
Expected: FAIL — `previewed_session_editable_refs[-1]` is `frozenset()`, not `frozenset({"customer.Customer@1"})` (the engine doesn't track it yet)

- [ ] **Step 3: Implement**

In `cli/src/modelable/llm/conversation_engine.py`, add state in `__init__` (after `self._pending_synthesis: _PendingSynthesis | None = None` at line 63):

```python
        self._pending_synthesis: _PendingSynthesis | None = None
        self._session_editable_refs: set[str] = set()
```

Update `_execute_plan` (currently lines 195-218) to pass the accumulated set:

```python
        if isinstance(plan, ChangeSetPlan):
            reply = self.backend.preview_source_change(
                plan,
                self.pending_action_id,
                session_editable_refs=frozenset(self._session_editable_refs),
            )
            if reply.kind == "preview" and reply.change_set_id is not None:
                self._track_preview(reply)
                self._pending_change_plan = plan
            return reply
```

Update `_apply` (currently lines 220-226) to accumulate refs after a successful apply:

```python
    def _apply(self, action_id: str) -> ConversationReply:
        reply = self.backend.apply(action_id)
        if reply.kind == "applied":
            self._clear_pending_action()
            if reply.focused_ref is not None:
                self.focused_ref = reply.focused_ref
            self._session_editable_refs.update(item.ref for item in reply.changed)
        return reply
```

Update `reset` (currently lines 162-173) to clear the set:

```python
    def reset(self) -> None:
        if self._pending_request_id is not None:
            self.planner.cancel(self._pending_request_id)
        self.backend.reset()
        self.focused_ref = None
        self.history.clear()
        self.pending_action_id = None
        self.pending_operation_kind = None
        self._pending_change_plan = None
        self._pending_request_id = None
        self._pending_message = None
        self._pending_synthesis = None
        self._session_editable_refs.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_engine.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full backend + browser conversation suites**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation.py tests/test_browser_conversation.py tests/test_lsp_conversation_integration.py tests/test_lsp_conversation_service.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/llm/conversation_engine.py cli/tests/test_conversation_engine.py
git commit -m "feat(llm): let ConversationEngine carry editable refs across turns in a session"
```

---

### Task 4: Stop offering `RetireDefinition` until the language supports it

**Files:**
- Modify: `cli/src/modelable/llm/conversation_plan.py` (add a schema-filtering helper)
- Modify: `cli/src/modelable/llm/conversation_planner.py:27-67, 202-289` (system prompt + offline heuristic)
- Test: `cli/tests/test_conversation_plan.py`, existing planner tests

**Interfaces:**
- Produces: `conversation_plan_json_schema(*, exclude_operation_kinds: frozenset[str] = frozenset()) -> dict[str, object]`. `conversation_planner.py`'s `_request()` calls this with `exclude_operation_kinds=frozenset({"retire_definition"})`.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_conversation_plan.py`:

```python
def test_conversation_plan_json_schema_can_exclude_an_operation_kind() -> None:
    from modelable.llm.conversation_plan import conversation_plan_json_schema

    schema = conversation_plan_json_schema(exclude_operation_kinds=frozenset({"retire_definition"}))
    operation = schema["$defs"]["Operation"]

    assert "retire_definition" not in operation["discriminator"]["mapping"]
    assert all(item["$ref"] != "#/$defs/RetireDefinition" for item in operation["oneOf"])
    # Every other operation kind must still be present.
    assert "rename_definition" in operation["discriminator"]["mapping"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py -k exclude_operation_kind -v`
Expected: FAIL with `TypeError: conversation_plan_json_schema() got an unexpected keyword argument 'exclude_operation_kinds'`

- [ ] **Step 3: Implement**

In `cli/src/modelable/llm/conversation_plan.py`, change `conversation_plan_json_schema` (currently lines 380-384):

```python
def conversation_plan_json_schema(*, exclude_operation_kinds: frozenset[str] = frozenset()) -> dict[str, object]:
    schema = _CONVERSATION_PLAN_ADAPTER.json_schema()
    _close_object_schemas(schema)
    _require_discriminators(schema)
    if exclude_operation_kinds:
        _exclude_operation_kinds(schema, exclude_operation_kinds)
    return schema


_OPERATION_KIND_TO_DEF_NAME: dict[str, str] = {
    "create_model": "CreateModel",
    "create_projection": "CreateProjection",
    "append_model_version": "AppendModelVersion",
    "append_projection_version": "AppendProjectionVersion",
    "add_field": "AddField",
    "rename_field": "RenameField",
    "remove_field": "RemoveField",
    "change_field_type": "ChangeFieldType",
    "set_field_optionality": "SetFieldOptionality",
    "set_field_annotations": "SetFieldAnnotations",
    "set_primary_index": "SetPrimaryIndex",
    "add_secondary_index": "AddSecondaryIndex",
    "remove_secondary_index": "RemoveSecondaryIndex",
    "set_projection_source": "SetProjectionSource",
    "add_projection_field": "AddProjectionField",
    "set_projection_mapping": "SetProjectionMapping",
    "add_projection_join": "AddProjectionJoin",
    "set_projection_filter": "SetProjectionFilter",
    "set_projection_grouping": "SetProjectionGrouping",
    "rename_definition": "RenameDefinition",
    "retire_definition": "RetireDefinition",
}


def _exclude_operation_kinds(schema: dict[str, object], kinds: frozenset[str]) -> None:
    operation = schema.get("$defs", {}).get("Operation")
    if not isinstance(operation, dict):
        return
    excluded_def_names = {_OPERATION_KIND_TO_DEF_NAME[kind] for kind in kinds if kind in _OPERATION_KIND_TO_DEF_NAME}
    mapping = operation.get("discriminator", {}).get("mapping")
    if isinstance(mapping, dict):
        for kind in kinds:
            mapping.pop(kind, None)
    one_of = operation.get("oneOf")
    if isinstance(one_of, list):
        operation["oneOf"] = [
            item for item in one_of if item.get("$ref", "").rsplit("/", 1)[-1] not in excluded_def_names
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py -v`
Expected: all PASS

- [ ] **Step 5: Write the failing test for the planner wiring**

Add to a planner test file (find the existing planner test module — search `grep -rn "class TestConversationPlanner\|def test_.*offline_plan\|ConversationPlanner._offline_plan" cli/tests/*.py` to locate it; if there is no dedicated file, add to `cli/tests/test_conversation_plan.py`):

```python
def test_planner_request_excludes_retire_definition() -> None:
    from modelable.llm.conversation_planner import PlannerContext, build_conversation_request

    request = build_conversation_request(
        message="retire the Customer model",
        context=PlannerContext(
            workspace_summary="domain customer\n  entity Customer @ 1",
            focused_ref=None,
            history=(),
            pending_plan=None,
        ),
    )

    assert '"retire_definition"' not in request.system


def test_offline_plan_classifies_retire_request_as_unsupported() -> None:
    from modelable.llm.conversation_plan import UnsupportedPlan
    from modelable.llm.conversation_planner import ConversationPlanner, PlannerContext

    context = PlannerContext(workspace_summary="", focused_ref=None, history=(), pending_plan=None)
    plan = ConversationPlanner._offline_plan("retire the Customer model", context)

    assert isinstance(plan, UnsupportedPlan)
    assert plan.roadmap_area == "operations"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py -k "retire_definition or retire_request" -v`
Expected: both FAIL (schema still includes `retire_definition`; offline heuristic misclassifies "retire" as a summary query)

- [ ] **Step 7: Implement**

In `cli/src/modelable/llm/conversation_planner.py`, change `_request()` (currently lines 396-423) to exclude the operation kind:

```python
def _request(
    *,
    message: str,
    context: PlannerContext,
    validation_error: str | None,
) -> LLMRequest:
    schema = conversation_plan_json_schema(exclude_operation_kinds=frozenset({"retire_definition"}))
```

(The rest of `_request` is unchanged; it already uses the local `schema` variable.)

Update the import at the top of the file (currently lines 13-24) since `conversation_plan_json_schema` is already imported — no import change needed there.

Add "retire" and "deprecate" to the offline heuristic's operational-edit-verb detection so it returns `UnsupportedPlan(roadmap_area="operations")` instead of falling through to a query. In `ConversationPlanner._offline_plan` (currently lines 202-289), add a check before the existing `add|create|change|...` regex (which currently sits at lines 242-246):

```python
        if re.search(r"\b(?:retire|deprecate)\b", lower):
            return UnsupportedPlan(
                request=message,
                reason=(
                    "Definition retirement isn't supported yet: the .mdl language has no "
                    "published-contract retirement declaration."
                ),
                roadmap_area="operations",
            )
        if re.search(
            r"\b(?:add|create|change|rename|remove|delete|set|update|replace|make)\b",
            lower,
        ):
            return ConversationPlanner._provider_required(message)
```

Also update the `SYSTEM_PROMPT` string (currently lines 27-67) to remove any implication that retirement is available — it currently doesn't mention retirement by name, so no prompt text change is needed there beyond what Task 5 covers.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py -v`
Expected: all PASS

- [ ] **Step 9: Run the full conversation-planner and workspace-editor suites for regressions**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_engine.py tests/test_conversation.py tests/test_workspace_editor.py -v`
Expected: all PASS (the `RetireDefinition` operation type and its `workspace_editor.py` handling are untouched — only the planner-facing schema/heuristic changed)

- [ ] **Step 10: Commit**

```bash
git add cli/src/modelable/llm/conversation_plan.py cli/src/modelable/llm/conversation_planner.py cli/tests/test_conversation_plan.py
git commit -m "fix(llm): stop offering retire_definition until the language supports it"
```

---

### Task 5: Complete the planner system prompt (draft-mode rules + CEL syntax)

**Files:**
- Modify: `cli/src/modelable/llm/conversation_planner.py:27-67`
- Test: `cli/tests/test_conversation_plan.py`

**Interfaces:**
- No signature changes — this task only changes prompt text and adds a text-content assertion test, since prompt wording can't be behavior-tested without a real LLM.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_conversation_plan.py`:

```python
def test_system_prompt_documents_draft_mode_for_every_mutating_operation() -> None:
    from modelable.llm.conversation_planner import SYSTEM_PROMPT

    for phrase in (
        "rename_field",
        "change_field_type",
        "set_primary_index",
        "add_secondary_index",
        "rename_definition",
        'edit_mode "draft"',
    ):
        assert phrase in SYSTEM_PROMPT, f"system prompt is missing guidance for {phrase!r}"


def test_system_prompt_documents_cel_equality_syntax() -> None:
    from modelable.llm.conversation_planner import SYSTEM_PROMPT

    assert "CEL" in SYSTEM_PROMPT
    assert "==" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py -k "draft_mode_for_every or cel_equality" -v`
Expected: FAIL — the current prompt only documents append-version rules for `add_field`/`create_model`, and never mentions CEL

- [ ] **Step 3: Implement**

Replace the `SYSTEM_PROMPT` string in `cli/src/modelable/llm/conversation_planner.py` (currently lines 27-67) with:

```python
SYSTEM_PROMPT = """You plan grounded requests against a Modelable workspace.
Return JSON only matching the supplied closed schema. Return exactly one of the five plan kinds:
- QueryPlan with kind "query" for deterministic workspace facts.
- ChangeSetPlan with kind "change_set" for typed workspace edits.
- CompilePlan with kind "compile" only for local generation in the current workspace.
- ClarificationPlan with kind "clarification" when required intent is ambiguous.
- UnsupportedPlan with kind "unsupported" when the request is outside planning.

Ask for clarification instead of assuming ambiguous ownership, identity fields,
whether an address is inline or a reusable address model, or a projection source.

Published-version immutability: any version listed in the "Workspace summary" is
existing and immutable in "append_versions" mode (the default ChangeSetPlan.edit_mode).
This applies to every mutating operation, not only field additions:
- create_model / create_projection: no restriction, these create brand-new versions.
- append_model_version / append_projection_version: always allowed; this is how you
  target a new version of an existing definition. If the summary shows `Model @ N`,
  new fields or changes must target `Model @ N+1` via append_model_version.
- add_field, remove_field, change_field_type, set_field_optionality,
  set_field_annotations, set_primary_index, add_secondary_index,
  remove_secondary_index, set_projection_source, add_projection_field,
  set_projection_mapping, add_projection_join, set_projection_filter,
  set_projection_grouping: these may target a version created earlier in the SAME
  conversation without a new version bump. Targeting any OTHER existing published
  version requires either appending a new version first, or setting
  ChangeSetPlan.edit_mode to "draft" (which rewrites the version in place and is
  only appropriate when the user explicitly asks to edit a specific version directly).
- rename_definition: always requires edit_mode "draft"; it is a whole-definition
  rename, never associated with a version bump.

Projection `on`/`where`/filter and grouping expressions are CEL, not `.mdl` field
syntax: equality is `==`, not `=`. For example, use
`c.customerId == c2.customerId`, never `c.customerId = c2.customerId`. A single `=`
will fail to parse.

If a model change might affect existing projections, use ClarificationPlan to
ask if the projections should be updated or mention the impact.

Use ChangeSetPlan, never CompilePlan, when the user asks to create or change
Modelable models, projections, fields, indexes, or annotations. CompilePlan is
only for generating artifacts from an already-defined workspace.

Examples:
{"kind":"change_set","summary":"Create billing.Invoice@1","operations":[{"kind":"create_model","domain":"billing","name":"Invoice","model_kind":"entity","fields":[{"name":"invoiceId","type":{"kind":"uuid"},"annotations":[{"kind":"key"}]}]}]}
{"kind":"change_set","summary":"Create billing.CustomerProjection@1","operations":[{"kind":"create_projection","domain":"billing","name":"CustomerProjection","source":{"model":"customer.Customer","version":1,"alias":"customer"},"fields":[{"name":"customerId","mapping":{"kind":"direct","source_alias":"customer","source_field":"customerId"}}]}]}
{"kind":"change_set","summary":"Add score in customer.Customer@3","operations":[{"kind":"append_model_version","source":"customer.Customer@2","version":3},{"kind":"add_field","target":"customer.Customer@3","field":{"name":"score","type":{"kind":"int"},"optional":true}}]}
{"kind":"change_set","summary":"Rename Customer to Client","edit_mode":"draft","operations":[{"kind":"rename_definition","target":"customer.Customer","new_name":"Client"}]}
{"kind":"change_set","summary":"Join CustomerProjection on customerId","operations":[{"kind":"add_projection_join","target":"billing.CustomerProjection@1","join":{"model":"customer.Customer","version":1,"alias":"c2","on":"c.customerId == c2.customerId","join_kind":"inner"}}]}
{"kind":"clarification","question":"Which source model and consumer domain should I use?","reason":"A projection requires a grounded source and consumer."}
{"kind":"clarification","question":"I see customer.CustomerProjection@1 depends on this model. Should I also update it?","reason":"Model changes impact downstream projections."}
CompilePlan permits only a target, domain filters, a normalized local relative output,
the descriptor flag, and a summary. Examples:
{"kind":"compile","target":"rust","domains":[],"output":null,"descriptor_set":false,"summary":"Compile the workspace to Rust."}
{"kind":"compile","target":"json-schema","domains":["customer"],"output":"dist/contracts","descriptor_set":false,"summary":"Compile customer JSON Schema."}
{"kind":"compile","target":"protobuf","domains":[],"output":null,"descriptor_set":true,"summary":"Compile Protobuf descriptors."}
Sync, publish, deployment, URL, credential, registry, remote requests, and arbitrary or external filesystem operations
are unsupported. Shell commands and other external operations are also unsupported.
Return UnsupportedPlan with roadmap_area "operations".
Never emit raw patches, workspace source paths, shell commands, validation overrides,
sync/publish actions, or any external action escape hatch.
Do not include markdown fences, prose, or commentary outside the JSON object.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full LLM test suite for regressions**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py tests/test_conversation_engine.py tests/test_conversation.py tests/test_ollama_conversation_conformance.py -v`
Expected: all PASS (this task only changes prompt text, which no existing test asserts the exact previous wording of — confirm this by checking `grep -n "SYSTEM_PROMPT" cli/tests/*.py` shows no other exact-match assertions before committing)

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/llm/conversation_planner.py cli/tests/test_conversation_plan.py
git commit -m "docs(llm): document draft-mode rules for every operation and CEL join/filter syntax"
```

---

### Task 6: `engine.py` conflict handling raises instead of silently skipping

**Files:**
- Modify: `cli/src/modelable/llm/engine.py:593-675, 727-807`
- Test: `cli/tests/test_llm_features.py`, `cli/tests/test_llm_provider_integration.py`

**Interfaces:**
- No signature changes to `_apply_model_change`, `_apply_projection_change`, `_apply_model_update`, `_apply_projection_update` — only their conflict branches change from "append a warning and return `False`" to "raise `ValueError`". This task runs before Task 7 removes these functions entirely, so it fixes the behavior for the current callers first and gives an isolated, revertable commit.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_llm_provider_integration.py` (near the existing `test_update_definition_uses_injected_provider` at line 226):

```python
def test_update_definition_raises_instead_of_silently_skipping_a_conflicting_add(tmp_path):
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

    class FakeProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            payload = {
                "target": "customer.Customer@1",
                "target_kind": "model",
                "warnings": [],
                "changes": [{"kind": "add_field", "field": "email", "type": "string"}],
            }
            return LLMResponse(content=json.dumps(payload), provider="ollama", model="llama3.1")

    with pytest.raises(ValueError, match="already exists"):
        update_definition(
            tmp_path,
            "customer.Customer@1",
            "add email as string",
            provider=FakeProvider(),
            write=False,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_llm_provider_integration.py -k raises_instead_of_silently -v`
Expected: FAIL — no exception is raised today; `update_definition` returns a result with a warning instead

- [ ] **Step 3: Implement**

In `cli/src/modelable/llm/engine.py`, change the conflict branches in `_apply_model_change` (currently lines 593-629):

```python
def _apply_model_change(version: ModelVersion, change: UpdateChange) -> tuple[bool, list[str]]:
    field = next((item for item in version.fields if item.name == change.field), None)
    warnings: list[str] = []
    if change.kind == "add_field":
        field_name = change.new_name or change.field
        if any(item.name == field_name for item in version.fields):
            raise ValueError(f"Field '{field_name}' already exists on {version.version}")
        version.fields.append(
            FieldDef(
                name=field_name,
                type=_type_from_text(change.type) or _string_field(),
                optional=False,
            )
        )
        return True, warnings
    if field is None:
        raise ValueError(f"Field '{change.field}' not found on {version.version}; cannot {change.kind}")
    if change.kind == "make_optional":
```

(Leave the rest of the function's non-conflict branches — `make_optional`, `make_required`, `rename_field`, `remove_field`, `change_type` — unchanged.)

Change `_apply_projection_change` (currently lines 632-675) the same way:

```python
def _apply_projection_change(version: ProjectionVersion, change: UpdateChange) -> tuple[bool, list[str]]:
    field = next((item for item in version.fields if item.name == change.field), None)
    warnings: list[str] = []
    if change.kind == "add_field":
        field_name = change.new_name or change.field
        if any(item.name == field_name for item in version.fields):
            raise ValueError(f"Field '{field_name}' already exists on {version.version}")
        version.fields.append(
            ProjectionField(
                name=field_name,
                mapping=DirectMapping(
                    source_alias=version.source.alias,
                    source_field=_normalize_source_field(change.source or field_name),
                ),
            )
        )
        return True, warnings
    if field is None:
        raise ValueError(f"Field '{change.field}' not found on {version.version}; cannot {change.kind}")
```

(Leave `rename_field`, `remove_field`, `change_source` unchanged; `change_type` and `make_optional`/`make_required` on projections stay as "unsupported operation" warnings since those are capability gaps, not conflicts — leave those two `warnings.append(...); return False, warnings` branches exactly as they are.)

Change the heuristic (no-provider) equivalents `_apply_model_update` (currently lines 727-767) and `_apply_projection_update` (currently lines 770-807) the same way — replace their `warnings.append(f"Field '{field_name}' already exists; skipped add")` branches with a raise:

```python
    add_match = _extract_field_addition(instruction)
    if add_match is not None:
        field_name, field_type, optional = add_match
        if any(field.name == field_name for field in version.fields):
            raise ValueError(f"Field '{field_name}' already exists on {version.version}")
        version.fields.append(
            FieldDef(
                name=field_name,
                type=field_type or _string_field(),
                optional=optional,
            )
        )
        updated = True
```

and the matching block in `_apply_projection_update`:

```python
    add_match = _extract_projection_field_addition(instruction)
    if add_match is not None:
        field_name, source_field = add_match
        if any(field.name == field_name for field in version.fields):
            raise ValueError(f"Field '{field_name}' already exists on {version.version}")
        version.fields.append(
            ProjectionField(
                name=field_name,
                mapping=DirectMapping(
                    source_alias=version.source.alias,
                    source_field=_normalize_source_field(source_field or field_name),
                ),
            )
        )
        updated = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_llm_provider_integration.py -k raises_instead_of_silently -v`
Expected: PASS

- [ ] **Step 5: Search for and update any test that currently asserts the old skip-and-warn text**

Run: `cd cli && grep -rn "already exists; skipped\|not found; skipped" tests/*.py`

For each match, read the surrounding test and change its assertion from expecting the warning string to expecting a raised `ValueError` with `match="already exists"` or `match="not found"`, following the pattern in Step 1's new test.

- [ ] **Step 6: Run the full LLM feature and provider-integration suites**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_llm_features.py tests/test_llm_provider_integration.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add cli/src/modelable/llm/engine.py cli/tests/test_llm_provider_integration.py cli/tests/test_llm_features.py
git commit -m "fix(llm): raise on conflicting field edits in engine.py instead of silently skipping"
```

---

### Task 7: Rewire `modelable llm update` through `ConversationSession`

This is the largest task. It replaces `update_definition()`'s internals (the separate `UpdatePlan`/`UpdateChange` schema and the heuristic regex path) with the shared `ConversationSession`/`WorkspaceEditor` path used by CLI chat, VS Code, and the web playground — while keeping `update_definition()`'s external signature and `UpdateResult` shape unchanged, since `cli/src/modelable/commands/llm.py` depends on both.

**Files:**
- Modify: `cli/src/modelable/llm/conversation_planner.py` (`PlannerContext`)
- Modify: `cli/src/modelable/llm/conversation_engine.py` (`begin_turn`)
- Modify: `cli/src/modelable/llm/conversation.py` (`ConversationSession.turn`)
- Modify: `cli/src/modelable/llm/engine.py` (`update_definition`, remove obsolete functions)
- Delete: `cli/src/modelable/llm/update_plan.py`
- Modify: `cli/src/modelable/llm/__init__.py` (remove re-exports)
- Modify tests: `cli/tests/test_llm_provider_integration.py`, `cli/tests/test_llm_features.py`

**Interfaces:**
- Produces: `PlannerContext` gains `direct_edit_mode: bool = False`. `ConversationEngine.begin_turn(self, message: str, *, direct_edit_mode: bool = False)`. `ConversationSession.turn(self, message: str, *, direct_edit_mode: bool = False)`. When `direct_edit_mode` is true and `context.focused_ref` is set, the planner is instructed to rewrite that ref in place with `edit_mode="draft"` rather than appending a version — this is what lets `update_definition()` reuse the shared engine for its "edit this exact named ref" contract.

- [ ] **Step 1: Add `direct_edit_mode` to `PlannerContext` and the request builder — write the failing test**

Add to `cli/tests/test_conversation_plan.py`:

```python
def test_request_includes_direct_edit_instruction_when_flagged() -> None:
    from modelable.llm.conversation_planner import PlannerContext, build_conversation_request

    request = build_conversation_request(
        message="make email optional",
        context=PlannerContext(
            workspace_summary="domain customer\n  entity Customer @ 1",
            focused_ref="customer.Customer@1",
            history=(),
            pending_plan=None,
            direct_edit_mode=True,
        ),
    )

    assert "customer.Customer@1" in request.user
    assert "draft" in request.user
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py -k direct_edit_instruction -v`
Expected: FAIL — `TypeError: PlannerContext.__init__() got an unexpected keyword argument 'direct_edit_mode'`

- [ ] **Step 3: Implement `PlannerContext` and `_request`**

In `cli/src/modelable/llm/conversation_planner.py`, change the `PlannerContext` dataclass (currently lines 70-75):

```python
@dataclass(frozen=True)
class PlannerContext:
    workspace_summary: str
    focused_ref: str | None
    history: tuple[tuple[str, str], ...]
    pending_plan: ChangeSetPlan | None
    direct_edit_mode: bool = False
```

Change `_request` (currently lines 396-423) to add the direct-edit instruction line:

```python
def _request(
    *,
    message: str,
    context: PlannerContext,
    validation_error: str | None,
) -> LLMRequest:
    schema = conversation_plan_json_schema(exclude_operation_kinds=frozenset({"retire_definition"}))
    lines = [f"Workspace summary:\n{context.workspace_summary}"]
    lines.append(f"Focused reference: {context.focused_ref or 'none'}")
    if context.direct_edit_mode and context.focused_ref is not None:
        lines.append(
            f'Direct edit mode: rewrite {context.focused_ref} in place using ChangeSetPlan.edit_mode "draft" '
            "for any change_set operations; do not append a new version."
        )
    if context.history:
```

(The rest of the function is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_plan.py -v`
Expected: all PASS

- [ ] **Step 5: Thread `direct_edit_mode` through `ConversationEngine.begin_turn` — write the failing test**

Add to `cli/tests/test_conversation_engine.py`:

```python
def test_begin_turn_forwards_direct_edit_mode_to_planner_context() -> None:
    captured_contexts: list[PlannerContext] = []

    class CapturingPlanner:
        def offline(self, message, context):
            captured_contexts.append(context)
            return ConversationPlanner._offline_plan(message, context)

        def begin(self, message, context):
            captured_contexts.append(context)
            return ConversationPlanner._offline_plan(message, context)

    engine = ConversationEngine(backend=RecordingBackend(), planner=CapturingPlanner())
    engine.begin_turn("make email optional", direct_edit_mode=True)

    assert captured_contexts[-1].direct_edit_mode is True
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_engine.py -k forwards_direct_edit_mode -v`
Expected: FAIL — `TypeError: begin_turn() got an unexpected keyword argument 'direct_edit_mode'`

- [ ] **Step 7: Implement**

In `cli/src/modelable/llm/conversation_engine.py`, change `begin_turn`'s signature and the `PlannerContext` construction (currently lines 65-125):

```python
    def begin_turn(self, message: str, *, direct_edit_mode: bool = False) -> ConversationOutcome:
```

(keep the body identical until the `PlannerContext` construction, currently lines 110-115):

```python
        context = PlannerContext(
            workspace_summary=self.backend.workspace_summary(focused_ref=self.focused_ref),
            focused_ref=self.focused_ref,
            history=tuple(self.history),
            pending_plan=self._pending_change_plan,
            direct_edit_mode=direct_edit_mode,
        )
```

- [ ] **Step 8: Run test to verify it passes, then thread through `ConversationSession.turn`**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_engine.py -v`
Expected: all PASS

In `cli/src/modelable/llm/conversation.py`, change `turn`'s signature (currently line 130) and its `begin_turn` call (currently line 141):

```python
    def turn(self, message: str, *, direct_edit_mode: bool = False) -> ConversationReply:
        try:
            normalized = message.strip()
            lowered = normalized.lower()
            if (
                self.backend.pending is None
                and self.backend.cleanup_action_id is not None
                and (lowered in {"discard", "discard it", "cancel"} or normalized == "/discard")
            ):
                reply = self.backend.discard(self.backend.cleanup_action_id)
                return self.engine.record_completed_reply(message, reply)
            outcome = self.engine.begin_turn(message, direct_edit_mode=direct_edit_mode)
```

- [ ] **Step 9: Run the full conversation suite**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation_engine.py tests/test_conversation.py -v`
Expected: all PASS

- [ ] **Step 10: Commit the plumbing**

```bash
git add cli/src/modelable/llm/conversation_planner.py cli/src/modelable/llm/conversation_engine.py cli/src/modelable/llm/conversation.py cli/tests/test_conversation_plan.py cli/tests/test_conversation_engine.py
git commit -m "feat(llm): add direct_edit_mode so a caller can pin edits to a named ref in draft mode"
```

- [ ] **Step 11: Rewrite `update_definition()` — write the failing tests**

Replace the three tests in `cli/tests/test_llm_provider_integration.py` that use the old `UpdatePlan` schema (`test_update_definition_uses_injected_provider` at line 226, `test_update_definition_repairs_invalid_provider_output` at line 266, `test_update_definition_can_disable_repair_attempts` at line 314) with:

```python
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

    def change_set_payload() -> str:
        return json.dumps(
            {
                "kind": "change_set",
                "summary": "Update customer.Customer@1",
                "edit_mode": "draft",
                "assumptions": ["review classification on email"],
                "operations": [
                    {
                        "kind": "set_field_optionality",
                        "target": "customer.Customer@1",
                        "field": "email",
                        "optional": True,
                    },
                    {
                        "kind": "add_field",
                        "target": "customer.Customer@1",
                        "field": {"name": "loyaltyTier", "type": {"kind": "string"}},
                    },
                ],
            }
        )

    class FakeProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(content=change_set_payload(), provider="ollama", model="llama3.1")

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
                "kind": "change_set",
                "summary": "Update customer.Customer@1",
                "edit_mode": "draft",
                "assumptions": ["repaired output"],
                "operations": [
                    {
                        "kind": "set_field_optionality",
                        "target": "customer.Customer@1",
                        "field": "email",
                        "optional": True,
                    }
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
    assert mdl.read_text(encoding="utf-8") == original
    assert not _provenance_path(mdl).exists()


def test_update_definition_requires_a_configured_provider(tmp_path):
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

    with pytest.raises(ValueError, match="requires an LLM provider"):
        update_definition(
            tmp_path,
            "customer.Customer@1",
            "make email optional",
            provider=None,
            llm_config=LlmConfig(provider=None, model=None, base_url=None, repair_attempts=1, source="workspace"),
            write=False,
        )

    assert not _provenance_path(mdl).exists()
```

Delete `test_update_definition_can_disable_repair_attempts` (lines 314-348) — the shared engine's `ResumableConversationPlanner` already has its own repair-attempt tests in `test_conversation_engine.py`; re-testing that mechanism through `update_definition` would duplicate coverage rather than test anything specific to this function.

- [ ] **Step 12: Run tests to verify they fail**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_llm_provider_integration.py -k "update_definition" -v`
Expected: FAIL — `update_definition` still expects `UpdatePlan`-shaped JSON and never raises "requires an LLM provider"

- [ ] **Step 13: Implement the new `update_definition`**

In `cli/src/modelable/llm/engine.py`:

Remove these now-obsolete functions entirely: `_build_update_plan`, `_parse_update_plan_response`, `_apply_update_plan_to_model`, `_apply_update_plan_to_projection`, `_apply_model_change`, `_apply_projection_change`, `_apply_model_update`, `_apply_projection_update`, `_extract_field_addition`, `_extract_projection_field_addition`, `_extract_rename`, `_extract_type_change`, `_matches_source_field_change`, `_extract_source_field`, `_normalize_source_field`, `_matches_optional`, `_matches_required`, `_matches_remove`, `_type_from_text`. Also remove the now-unused `UpdatePlanResult` dataclass (keep `UpdateResult` — it is still the return type).

Remove the now-unused imports at the top of the file: `from modelable.llm.update_plan import (...)`, and the `re` import if nothing else in the file uses it (check with `grep -n "\bre\." cli/src/modelable/llm/engine.py` after the removal — `_extract_rename`/`_extract_type_change` were the only users of the local `import re` statements inside those functions; the top-level `import re` at line 4 is also now unused, so remove it too if the grep confirms no remaining use).

Add the new import:

```python
from modelable.llm.conversation import ConversationSession
```

Replace `update_definition` (currently lines 299-391) with:

```python
def update_definition(
    path: Path,
    ref: str,
    instruction: str,
    *,
    output: Path | None = None,
    write: bool = True,
    provider: LLMProvider | None = None,
    llm_config: LlmConfig | None = None,
) -> UpdateResult:
    workspace = load_workspace(path)
    model_ref = parse_model_ref(ref)
    source_path = _find_source_path_for_ref(workspace, model_ref.domain, model_ref.name)
    if source_path is None:
        raise ValueError(f"Could not find source file for {ref}")
    original_text = source_path.read_text(encoding="utf-8")

    if llm_config is None:
        llm_config = resolve_llm_config(workspace=workspace.mdl.workspace, env=environ)
    provider_name = llm_config.provider or "local"
    model_name = llm_config.model or "modelable-local"
    if provider is None:
        provider = build_provider(llm_config.provider, model=llm_config.model, base_url=llm_config.base_url)
    if provider is None:
        raise ValueError(
            "modelable llm update requires an LLM provider; configure one with --provider/--model "
            "or workspace/environment configuration."
        )

    session = ConversationSession(
        path=path,
        provider=provider,
        focused_ref=ref,
        repair_attempts=llm_config.repair_attempts,
        provider_name=provider_name,
        model_name=model_name,
        confirmation_surface="cli-chat",
    )
    try:
        reply = session.turn(instruction, direct_edit_mode=True)
        if reply.kind != "preview" or reply.operation_kind != "source_change":
            raise ValueError(f"Could not apply the update instruction: {reply.text}")
        preview_file = next((item for item in reply.preview_files if item.path == source_path), None)
        if preview_file is None:
            raise ValueError(f"Update instruction did not change {source_path}")
        new_text = preview_file.after_text
        change_set_id = reply.change_set_id
        assert change_set_id is not None
        if not write:
            session.engine.discard(change_set_id)
            return UpdateResult(
                path=output or source_path,
                source_path=source_path,
                ref=ref,
                original_content=original_text,
                content=new_text,
                warnings=list(reply.assumptions),
                provider=provider_name,
                model=model_name,
                diagnostics_repaired=0,
            )
        applied = session.engine.apply(change_set_id)
        if applied.kind != "applied":
            raise ValueError(f"Could not apply the update instruction: {applied.text}")
    finally:
        session.close()

    out_path = output or source_path
    if output is not None and output != source_path:
        output.write_text(new_text, encoding="utf-8")
    return UpdateResult(
        path=out_path,
        source_path=source_path,
        ref=ref,
        original_content=original_text,
        content=new_text,
        warnings=list(reply.assumptions),
        provider=provider_name,
        model=model_name,
        diagnostics_repaired=0,
    )
```

- [ ] **Step 14: Run tests to verify they pass**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_llm_provider_integration.py -k "update_definition" -v`
Expected: all PASS

- [ ] **Step 15: Delete `update_plan.py` and its re-exports**

Delete `cli/src/modelable/llm/update_plan.py`.

In `cli/src/modelable/llm/__init__.py`, remove line 26 (`from .update_plan import UpdateChange, UpdatePlan, build_update_request, parse_update_plan`) and the corresponding `__all__` entries `"UpdateChange"`, `"UpdatePlan"`, and `"parse_update_plan"` (check the `__all__` list around lines 46-55 for the exact entries and remove all four names, including `build_update_request` if listed).

- [ ] **Step 16: Run the whole test suite for import errors**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/ -x -q 2>&1 | tail -60`
Expected: no `ImportError`/`ModuleNotFoundError` for `update_plan`; note any remaining failures for Step 17

- [ ] **Step 17: Update the remaining CLI-level tests that exercised the old no-provider heuristic**

The following tests in `cli/tests/test_llm_features.py` currently invoke `modelable update <ref> <instruction> --path ...` with no `--provider` flag, relying on the now-removed offline heuristic: `test_cli_update_model_field` (line 1036), `test_cli_update_preview_shows_diff_without_writing` (line 1074), `test_cli_update_projection_field` (line 1107). Rewrite each to inject a fake provider via `monkeypatch.setattr("modelable.commands.llm.build_provider", ...)` so the CLI command path is still exercised end-to-end without a real network call. Replace all three with:

```python
def test_cli_update_model_field(tmp_path, monkeypatch):
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

    class FakeProvider:
        def complete(self, request):
            from modelable.llm.providers import LLMResponse

            payload = json.dumps(
                {
                    "kind": "change_set",
                    "summary": "Update customer.Customer@1",
                    "edit_mode": "draft",
                    "operations": [
                        {
                            "kind": "set_field_optionality",
                            "target": "customer.Customer@1",
                            "field": "email",
                            "optional": True,
                        },
                        {
                            "kind": "add_field",
                            "target": "customer.Customer@1",
                            "field": {"name": "loyaltyTier", "type": {"kind": "string"}},
                        },
                    ],
                }
            )
            return LLMResponse(content=payload, provider="fake", model="test-model")

    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FakeProvider())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "update",
            "customer.Customer@1",
            "make email optional and add loyaltyTier as string",
            "--path",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "audit:" in result.output
    provenance = _read_provenance(_provenance_path(mdl))
    assert provenance["command"] == "update"
    assert provenance["inputs"]["ref"] == "customer.Customer@1"
    updated = mdl.read_text(encoding="utf-8")
    assert "email?: string" in updated
    assert "loyaltyTier: string" in updated


def test_cli_update_preview_shows_diff_without_writing(tmp_path, monkeypatch):
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
        def complete(self, request):
            from modelable.llm.providers import LLMResponse

            payload = json.dumps(
                {
                    "kind": "change_set",
                    "summary": "Update customer.Customer@1",
                    "edit_mode": "draft",
                    "operations": [
                        {
                            "kind": "set_field_optionality",
                            "target": "customer.Customer@1",
                            "field": "email",
                            "optional": True,
                        }
                    ],
                }
            )
            return LLMResponse(content=payload, provider="fake", model="test-model")

    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FakeProvider())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "update",
            "customer.Customer@1",
            "make email optional",
            "--path",
            str(tmp_path),
            "--preview",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "@@" in result.output
    assert "-    email: string" in result.output
    assert "+    email?: string" in result.output
    assert mdl.read_text(encoding="utf-8") == original
    assert not _provenance_path(mdl).exists()


def test_cli_update_projection_field(tmp_path, monkeypatch):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}

domain billing {
  owner: "test-team"
  projection CustomerBrief @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )

    class FakeProvider:
        def complete(self, request):
            from modelable.llm.providers import LLMResponse

            payload = json.dumps(
                {
                    "kind": "change_set",
                    "summary": "Update billing.CustomerBrief@1",
                    "edit_mode": "draft",
                    "operations": [
                        {
                            "kind": "rename_field",
                            "target": "billing.CustomerBrief@1",
                            "field": "name",
                            "new_name": "displayName",
                        },
                        {
                            "kind": "add_projection_field",
                            "target": "billing.CustomerBrief@1",
                            "field": {
                                "name": "status",
                                "mapping": {"kind": "direct", "source_alias": "c", "source_field": "name"},
                            },
                        },
                    ],
                }
            )
            return LLMResponse(content=payload, provider="fake", model="test-model")

    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FakeProvider())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "update",
            "billing.CustomerBrief@1",
            "rename name to displayName and add status from c.name",
            "--path",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    provenance = _read_provenance(_provenance_path(mdl))
    assert provenance["command"] == "update"
    updated = mdl.read_text(encoding="utf-8")
    assert "displayName <- c.name" in updated
    assert "status <- c.name" in updated
```

Note: `test_cli_update_model_field`'s `field: email` is directly on `customer.Customer@1`, which is an existing published version — this requires the planner to have been told to use `edit_mode="draft"`, which is exactly what `direct_edit_mode=True` (wired through `update_definition` in Step 13) instructs it to do via the prompt line added in Step 3. If this test's `FakeProvider` didn't set `"edit_mode": "draft"` explicitly, the fake response would still be accepted by the schema (it's a valid field on the real LLM's response, not something `ConversationEngine` enforces) — the fake providers in tests must set it explicitly because tests don't run the real LLM that would read the prompt instruction.

- [ ] **Step 18: Rewrite the CLI provider-flag tests**

`test_update_command_uses_provider_flags` (`cli/tests/test_llm_provider_integration.py:818`) and `test_update_command_uses_anthropic_provider_flags` (right after it) fake the raw Ollama/Anthropic HTTP transport and feed `UpdatePlan`-shaped JSON. Update the JSON payload each constructs (the `captured`/`fake_urlopen`/equivalent Anthropic fake) to the same `ChangeSetPlan` shape used in Step 11's `change_set_payload()`, i.e. replace:

```python
                            "content": json.dumps(
                                {
                                    "target": "customer.Customer@1",
                                    "target_kind": "model",
                                    "warnings": ["provider-backed update"],
                                    "changes": [{"kind": "make_optional", "field": "email"}],
                                }
                            )
```

with:

```python
                            "content": json.dumps(
                                {
                                    "kind": "change_set",
                                    "summary": "Update customer.Customer@1",
                                    "edit_mode": "draft",
                                    "assumptions": ["provider-backed update"],
                                    "operations": [
                                        {
                                            "kind": "set_field_optionality",
                                            "target": "customer.Customer@1",
                                            "field": "email",
                                            "optional": True,
                                        }
                                    ],
                                }
                            )
```

in both tests (read each test's Anthropic-specific request/response envelope shape first — it wraps the same JSON content string inside a different outer transport envelope, so only the inner JSON string changes, not the surrounding fake-HTTP scaffolding).

- [ ] **Step 19: Run the full test suite**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -80`
Expected: all PASS. Investigate and fix any remaining failure before proceeding — do not skip or mark tests `xfail` to force this green.

- [ ] **Step 20: Run lint and type checks (per project convention)**

Run: `cd cli && .venv/Scripts/python.exe -m ruff format --check . && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m mypy src`
Fix any issues raised (unused imports from the deletions in Step 13/15 are the most likely finding).

- [ ] **Step 21: Commit**

```bash
git add cli/src/modelable/llm/engine.py cli/src/modelable/llm/__init__.py cli/tests/test_llm_provider_integration.py cli/tests/test_llm_features.py
git rm cli/src/modelable/llm/update_plan.py
git commit -m "feat(llm): rewire modelable llm update through the shared ConversationSession/WorkspaceEditor path"
```

---

### Task 8: Proactive "no provider configured" notice

**Files:**
- Modify: `cli/src/modelable/llm/conversation.py` (`ConversationSession`)
- Modify: `cli/src/modelable/commands/llm.py:533-599` (`chat` command)
- Modify: `cli/src/modelable/lsp/conversation_service.py:54-93` (`turn`)
- Test: `cli/tests/test_conversation.py`, `cli/tests/test_llm_provider_integration.py`, `cli/tests/test_lsp_conversation_integration.py`

**Interfaces:**
- Produces: `ConversationSession.no_provider_notice` (property) `-> str | None`. `None` when a provider is configured; otherwise a fixed, user-facing sentence. CLI and the VS Code LSP conversation service both consume this property; no change is made to `web/src/*` or VS Code `.js` files (the browser/VS Code UI wiring is out of scope for this plan per the design's non-goals — the browser has no equivalent `ConversationSession.provider` concept to check, since browser sessions never construct one).

- [ ] **Step 1: Write the failing test for the property**

Add to `cli/tests/test_conversation.py`:

```python
def test_no_provider_notice_is_none_when_a_provider_is_configured(tmp_path) -> None:
    (tmp_path / "workspace.mdl").write_text("", encoding="utf-8")

    class FakeProvider:
        def complete(self, request):
            raise AssertionError("not called")

    session = ConversationSession(path=tmp_path, provider=FakeProvider())
    assert session.no_provider_notice is None


def test_no_provider_notice_explains_the_limitation_when_absent(tmp_path) -> None:
    (tmp_path / "workspace.mdl").write_text("", encoding="utf-8")

    session = ConversationSession(path=tmp_path, provider=None)
    assert session.no_provider_notice is not None
    assert "provider" in session.no_provider_notice.lower()
```

(Add `from modelable.llm.conversation import ConversationSession` to the test file's imports if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation.py -k no_provider_notice -v`
Expected: FAIL with `AttributeError: 'ConversationSession' object has no attribute 'no_provider_notice'`

- [ ] **Step 3: Implement the property**

In `cli/src/modelable/llm/conversation.py`, add after the `focused_ref` property/setter pair (currently lines 102-108):

```python
    @property
    def no_provider_notice(self) -> str | None:
        if self.provider is not None:
            return None
        return (
            "No LLM provider is configured, so I can answer workspace queries but can't make edits. "
            "Configure a provider (--provider/--model, or workspace/environment configuration) to enable edits."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_conversation.py -v`
Expected: all PASS

- [ ] **Step 5: Wire it into the CLI `chat` command — write the failing test**

Add to `cli/tests/test_llm_provider_integration.py`:

```python
def test_chat_prints_no_provider_notice_once_at_startup(tmp_path, monkeypatch):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["chat", "--path", str(tmp_path), "--message", "/context"],
    )
    assert result.exit_code == 0, result.output
    assert "provider" in result.output.lower()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_llm_provider_integration.py -k no_provider_notice -v`
Expected: FAIL — today the CLI never prints anything about a missing provider unless an edit is attempted

- [ ] **Step 7: Implement**

In `cli/src/modelable/commands/llm.py`, in the `chat` function (currently lines 533-599), print the notice once right after constructing `session` and before the `try` block (currently the blank line before line 555):

```python
    session = ConversationSession(
        path=path,
        provider=llm_provider,
        focused_ref=ref,
        repair_attempts=config.repair_attempts,
        provider_name=config.provider,
        model_name=config.model,
        confirmation_surface="cli-chat",
    )
    if session.no_provider_notice is not None:
        console.print(f"[yellow]{session.no_provider_notice}[/yellow]")

    try:
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_llm_provider_integration.py -k no_provider_notice -v`
Expected: PASS

- [ ] **Step 9: Wire it into the VS Code LSP conversation service — write the failing test**

`cli/tests/test_lsp_conversation_service.py` already has a `_session_factory` (line 115) that builds every test session with `provider=None`, plus a `_turn_params`/`_write_customer_workspace` helper pair used throughout the file. Add this test using that exact existing fixture pattern:

```python
def test_first_turn_includes_no_provider_notice_when_unconfigured(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    service = LspConversationService(session_factory=_session_factory)

    reply = service.turn(_turn_params(root, create_session=True))

    assert reply["text"].startswith("No LLM provider is configured")
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_lsp_conversation_service.py -k no_provider_notice -v`
Expected: FAIL — today `reply["text"]` is just the answer text ("This workspace is valid." or similar), with no notice prefix

- [ ] **Step 11: Implement**

In `cli/src/modelable/lsp/conversation_service.py`, in `turn` (currently lines 54-93), prepend the notice on first-session-creation only. Change the block that creates a new `entry` (currently lines 65-79) and the reply construction (currently line 91):

```python
        entry = self._sessions.get(params.session_id)
        is_new_session = entry is None
        if entry is None:
            if not params.create_session:
                raise ConversationSessionError(
                    f"Conversation session {params.session_id} is unknown or expired; start a new session."
                )
            self._evict_if_full()
            focused_ref = self._focused_ref(params, index)
            entry = _SessionEntry(
                workspace_uri=params.workspace_uri,
                root=root,
                session=self._new_session(root, focused_ref, params.session_id),
                touched_at=now,
            )
            self._sessions[params.session_id] = entry
        else:
            if params.create_session:
                raise ConversationSessionError(f"Conversation session {params.session_id} already exists.")
            if entry.root != root:
                raise ConversationSessionError(
                    f"Conversation session {params.session_id} belongs to a different workspace."
                )
            focused_ref = self._focused_ref(params, index)
            if focused_ref is not None:
                entry.session.focused_ref = focused_ref

        reply = entry.session.turn(params.message)
        entry.touched_at = now
        notice = entry.session.no_provider_notice
        if is_new_session and notice is not None:
            reply = replace(reply, text=f"{notice}\n\n{reply.text}")
        return self._serialize(reply, params.session_id, entry)
```

(`replace` is already imported at the top of the file from `dataclasses`.)

- [ ] **Step 12: Run test to verify it passes, and check for regressions in the rest of the file**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_lsp_conversation_service.py -v`
Expected: all PASS. Every other test in this file already uses `_session_factory`, which passes `provider=None` — so every one of them now gets the notice prepended to its first-turn reply text. None of them assert on the literal `reply["text"]` contents (only `reply["kind"]`, `reply["sessionId"]`, and similar structured fields), so this should not break anything; the full run confirms it.

Also run the real-subprocess integration suite, since it exercises the same `turn()` method via `LspConversationService._build_session()` (which resolves a provider from real workspace/environment config rather than a test factory, so it is unaffected unless the test environment happens to have no LLM provider configured):

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/test_lsp_conversation_integration.py -v`
Expected: all PASS

- [ ] **Step 13: Run the full test suite, lint, and type check**

Run: `cd cli && .venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -60 && .venv/Scripts/python.exe -m ruff format --check . && .venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m mypy src`
Expected: all PASS

- [ ] **Step 14: Commit**

```bash
git add cli/src/modelable/llm/conversation.py cli/src/modelable/commands/llm.py cli/src/modelable/lsp/conversation_service.py cli/tests/test_conversation.py cli/tests/test_llm_provider_integration.py cli/tests/test_lsp_conversation_service.py
git commit -m "feat(llm): surface a proactive no-provider notice in CLI chat and the VS Code conversation service"
```

---

## Final verification

- [ ] Run the entire CLI test suite once more from a clean state: `cd cli && .venv/Scripts/python.exe -m pytest tests/ -q`
- [ ] Run `ruff format --check .`, `ruff check .`, and `mypy src` from `cli/` — all must be clean.
- [ ] Re-read the design doc (`docs/superpowers/specs/2026-07-28-conversation-engine-editing-fixes-design.md`) section by section and confirm each numbered design point (1-6) has a corresponding completed task above:
  - Design §1 (session-scoped draft continuation) → Tasks 1-3
  - Design §2 (unify conflict semantics) → Tasks 6-7
  - Design §3 (RetireDefinition interim removal) → Task 4
  - Design §4 (planner prompt completeness) → Task 5
  - Design §5 (CEL syntax) → Task 5
  - Design §6 (offline/no-provider UX) → Task 8
