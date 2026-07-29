# Conversation Engine Editing Fixes — Design

**Date:** 2026-07-28

## Status

Proposed. First of three planned sub-projects toward a broader "LLM chat can
reliably edit the model, and the web playground reaches parity with CLI/VS
Code" initiative:

- **A (this design):** Engine correctness fixes — shared across CLI, VS Code,
  and the web playground.
- **B (future):** Definition-level retirement/deprecation as a real `.mdl`
  language feature (grammar, parser, compiler, emitters).
- **C (future):** Web playground chat UI parity pass (session persistence,
  provider configuration, slash commands, streaming, message rendering).

This design builds on the shared engine established in
[Shared Conversation Engine](archived/2026-07-27-shared-conversation-engine-design.md).

## Context

An empirical investigation drove the `ChangeSetPlan` apply path
(`cli/src/modelable/llm/workspace_editor.py`) directly against a temporary
workspace, bypassing the need for a live LLM, and found several concrete,
reproducible failure modes behind the "a lot of things doesn't work"
complaint. None of these are UI bugs — they live in the shared engine that
CLI, VS Code, and the web playground all call through, so fixing them here
benefits every surface.

Verified failures:

1. **Offline/no-provider mode cannot perform any edit.** Every common edit
   phrase ("add a field", "rename X", "remove Y", ...) is regex-matched by
   `ConversationPlanner._offline_plan` (`conversation_planner.py:242-246`) and
   returned as `UnsupportedPlan` telling the user to configure a provider.
   With no provider configured, every edit request is a silent-feeling no-op.
2. **`RetireDefinition` always throws.** It's a real operation the LLM can
   emit, but `workspace_editor.py:190-194` unconditionally raises
   `WorkspaceEditError` — there is no code path that can ever apply it,
   because the `.mdl` language has no definition-level retirement construct
   yet (only a field-level `@deprecated(replacedBy: ...)` annotation exists,
   scoped to `field_decl` in the grammar). The offline heuristic planner also
   doesn't recognize "retire" as an edit verb and misclassifies it as a query.
3. **Multi-turn edits to a just-created ref fail with a confusing error.**
   `editable_refs`, the set of refs allowed to bypass the immutable-version
   guard, is scoped to a single `preview()` call and does not persist across
   conversation turns. A user who adds a field in turn 1 (applied
   successfully) and asks to rename it in turn 2 hits: `Cannot edit existing
   model version ...; append a new version or use draft mode`
   (`workspace_editor.py:910-913`, `1132`, `1150`, `1304` — same guard reused
   throughout).
4. **The planner's system prompt is incomplete.** `conversation_planner.py:
   27-67` documents the append-version rule only for adding fields/models. It
   says nothing about `rename_field`, `change_field_type`, index changes, or
   `rename_definition`/`retire_definition` needing the same treatment (or
   `edit_mode="draft"` specifically) — so the LLM has no way to know and
   produces plans that get rejected after the fact.
5. **Projection join/filter expressions require CEL syntax**, e.g.
   `c.id == c2.id`, not `c.id = c2.id`. A single `=` fails with an opaque CEL
   parser error (`CEL001: parse error: unexpected token ...`). Nothing in the
   prompt states that `on`/`where` are CEL expressions.
6. **Two divergent apply implementations exist.** `cli/src/modelable/llm/
   engine.py` (used by the standalone `modelable llm update` CLI command)
   silently skips conflicting edits with a warning (e.g. `engine.py:599`,
   `:610`). The shared `ConversationEngine`/`WorkspaceEditor` path used by CLI
   chat, VS Code, and the web playground hard-errors on the same conflicts
   (e.g. `workspace_editor.py:916`). Same class of request, different
   surfaces, different outcomes — an accidental split, not a designed one.

## Goals

- Every edit request either succeeds, or fails with a reason the user
  understands *before* or *at* the point of failure — never a silent no-op
  and never a guaranteed-to-fail operation offered as if it might work.
- One conflict-handling semantics for LLM-driven edits, used by every entry
  point (CLI chat, VS Code, web playground, `modelable llm update`).
- No change to the language/compiler in this design — `RetireDefinition`'s
  real fix (a definition-level retirement construct) is scope B; this design
  only stops the engine from offering an operation guaranteed to fail.

## Non-Goals

- Implementing definition-level retirement/deprecation in the `.mdl`
  language (scope B).
- Web playground UI changes (scope C) — this design only touches
  `cli/src/modelable/llm/` and `cli/src/modelable/browser/conversation.py`'s
  shared backend logic, not `web/src/ai/*`.
- Adding a configurable local/Ollama provider to the web playground.

## Design

### 1. Session-scoped draft continuation

Today, `editable_refs` is rebuilt from scratch on every `preview()` call, so
it only allows follow-up operations to build on *earlier operations in the
same change-set*, never on a ref that a *previous, already-applied* turn in
the same conversation created or touched.

`ConversationEngine` (or `ConversationSession`/`BrowserConversationBackend`,
whichever owns per-session state today) will track a
`session_editable_refs: set[str]` that accumulates every ref created or
modified by an applied change-set in that session, and passes it into
`WorkspaceEditor.preview()`/`.apply()` alongside the per-call `editable_refs`.
While a ref is in that session-level set, further edits are treated as if
`edit_mode="draft"` for that ref specifically — no version bump required —
matching how a person would iterate on a field before considering it
"published." The set is per-session and in-memory only; it is discarded when
the session ends (CLI process exit, VS Code session close, web page/tab
session end) or if the user explicitly signals they're done iterating (see
below). Nothing changes about refs the session never touched — those keep
requiring a version bump or explicit `edit_mode="draft"`, exactly as today.

There is no separate "publish" command introduced by this design; the
existing session lifecycle (process exit / session close) is what ends the
draft-continuation window. If a durable "I'm done iterating, lock this in"
signal turns out to be needed in practice, that's a candidate for a later,
narrower follow-up — not speculated on here.

### 2. Unify conflict-handling semantics on hard errors

`cli/src/modelable/llm/engine.py`'s field-edit logic (the skip-and-warn
implementation backing `modelable llm update`) is removed. The command is
rewired to go through `ConversationSession`/`WorkspaceEditor` — the same path
CLI chat, VS Code, and the web playground already use — so a conflicting edit
raises the same `WorkspaceEditError` everywhere, with the same message. This
removes an entire parallel implementation rather than adding a flag to keep
both behaviors alive; nothing in the codebase depends on `llm update`
tolerating conflicts silently (no scripted/batch caller was found relying on
skip-and-warn semantics).

### 3. RetireDefinition — interim removal from the offered operation set

Until scope B implements the underlying language construct,
`ConversationPlanner` stops instructing the LLM that `retire_definition` is
available: it is removed from the planner's system prompt and JSON schema
presented to the model. A request that clearly asks for retirement/
deprecation of a whole model or projection returns `UnsupportedPlan(
roadmap_area="operations", reason="Definition retirement isn't supported yet")`
via the same offline-heuristic keyword path used for other unsupported
requests, rather than reaching `workspace_editor.py`'s guaranteed-throw code.
The `RetireDefinition` operation type and its `workspace_editor.py` handling
are left in place (harmless, unreachable from the planner) so scope B can
re-enable it by restoring the schema entry once the language feature exists,
without needing to re-derive the plumbing.

### 4. Planner system prompt completeness

Rewrite `conversation_planner.py:27-67` so that, for every operation kind, the
prompt states explicitly whether it requires `edit_mode="draft"` or a version
bump on a published target, folding in the session-scoped draft-continuation
behavior from (1) so the model understands it can keep editing a ref it
created earlier in the same conversation without asking for a bump. Add two
or three worked examples covering rename/retype/index changes specifically,
since those are the kinds most likely to be misjudged today (finding #4).

### 5. Document CEL syntax for join/filter expressions

Add an explicit statement to the same prompt: `on`, `where`, and grouping/
filter expressions are CEL, equality is `==` not `=`, with one worked example
(`c.customerId == c2.customerId`). This directly closes finding #5.

### 6. Offline/no-provider UX

When a `ConversationSession` or `BrowserConversationService` is constructed
with no provider configured (`build_provider(...)` returned `None`, or the
browser has neither WebLLM nor simulator initialized), the very first
response in that session proactively states the limitation once, before any
edit is attempted — e.g. "No LLM provider is configured, so I can answer
workspace queries but can't make edits. Configure a provider to enable
edits." — rather than only surfacing it as a rejection on the user's first
edit attempt. This is a messaging change in `ConversationEngine`/
`ConversationSession`, not a capability change: offline mode remains
query/read-only. Concretely: CLI prints this once at REPL startup; the LSP-
backed VS Code participant includes it as the first message in a new chat
session; the web playground's provider-state onboarding (already has a state
machine — see research) gets a parallel state for "no provider" shown before
the user's first chat attempt, which scope C will wire into the actual UI.

## Testing

- Unit tests for session-scoped draft continuation: apply a change-set that
  creates a field, then in a second turn (new `preview()` call) edit that
  same field without bumping the version or setting `edit_mode="draft"` —
  should succeed. A ref never touched by the session should still require a
  version bump, unchanged from today.
- Regression test for `RetireDefinition`: confirm the planner never emits
  `retire_definition` (schema/prompt no longer offers it) and that a
  retirement-shaped request returns `UnsupportedPlan` with
  `roadmap_area="operations"`, not a `WorkspaceEditError`.
  Also confirm the offline heuristic classifies "retire the Customer model"
  as `UnsupportedPlan`, not a stray `QueryPlan`.
- `modelable llm update` integration test: a conflicting field-add now raises
  the same `WorkspaceEditError` chat surfaces raise, instead of a silent
  skip-and-warn.
- Prompt-driven test (using the existing fake/test `LLMProvider` pattern from
  `test_conversation_engine.py`/`test_conversation_planner.py`): confirm a
  rename/retype/index-change request against a published version, and a
  projection join using `=` instead of `==`, both produce either a valid plan
  or a clear, actionable rejection — not a confusing internal error.
- No-provider startup message test for CLI, VS Code LSP session init, and the
  browser conversation service.

## Open Questions

None outstanding — all decisions above were confirmed during design review
(session-scoped draft continuation over prompt-only or clarification-based
alternatives; hard-error unification over preserving `engine.py`'s
skip-and-warn behavior; interim removal of `RetireDefinition` from the
offered operation set rather than leaving it reachable and broken).
