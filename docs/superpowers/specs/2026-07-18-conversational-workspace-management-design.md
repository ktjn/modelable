# Conversational Workspace Management — Design

Date: 2026-07-18

## 1. Purpose

Modelable already has an interactive `chat` command that can answer a limited
set of workspace questions and preview narrow edits to one existing model or
projection. The current implementation relies on message heuristics, passes a
text summary to an optional provider, and routes edit-like messages through the
single-definition `update` pipeline. It cannot create complete definitions,
coordinate changes across files, explain compatibility impact, or apply a
confirmed preview from the conversation.

This design turns the existing chat into a safe natural-language management
surface for contract analysis and authoring. A user should be able to ask about
workspace information, create whole entities and projections, revise contracts,
review an explained textual change set, and explicitly apply it.

The first delivery surface is the CLI. The planning and editing layers must be
independent of Click and reusable by a later VS Code chat/editor integration.

## 2. Goals

The first slice must:

- answer natural-language questions about models, projections, fields,
  ownership, lineage, indexes, compatibility, validation, and dependents;
- create complete entities and projections from short descriptions such as
  "add a customer entity with address";
- revise entities and projections through typed, deterministic edit
  operations;
- create a new version by default when changing an existing version;
- coordinate one atomic change set across multiple definitions and source
  files;
- show a textual unified diff, assumptions, compatibility findings, and
  affected definitions before any write;
- require explicit confirmation before applying the exact previewed change
  set;
- reject stale, invalid, or partially writable change sets without leaving a
  partially updated workspace;
- retain useful deterministic chat commands when no LLM provider is
  configured; and
- expose a reusable Python workspace-editor boundary for the CLI, language
  server, and future editor clients.

## 3. Non-Goals

This slice does not:

- add a VS Code chat UI;
- compile artifacts conversationally;
- synchronize registries;
- publish contracts or generated artifacts;
- call external catalog, lineage, schema-registry, or deployment services;
- allow the model to write raw source patches;
- turn chat into an autonomous agent that chooses or invokes arbitrary tools;
  or
- add authentication or authorization policy for remote operational actions.

VS Code integration and operational management are explicit roadmap
follow-ups. They build on this editor boundary but require separate UI,
authorization, and confirmation designs.

## 4. Architecture

The dependency direction is:

```text
CLI chat / future VS Code chat
  -> conversational planner
  -> workspace editor
  -> parser, IR, renderer, validator, compatibility and dependency analysis
```

The compiler remains the source of truth for parsing, normalized IR, semantic
validation, compatibility, and dependency analysis. The editor orchestrates
those compiler primitives; compiler code must not depend on chat, provider, or
conversation state.

### 4.1 Conversational planner

The planner converts one user message into exactly one typed result:

- `QueryPlan` for read-only workspace inspection;
- `ChangeSetPlan` for contract authoring;
- `ClarificationPlan` when required information cannot be inferred safely; or
- `UnsupportedPlan` when the request is outside this release.

Provider-backed planning uses schema-constrained responses and one structured
repair attempt when the response fails schema validation. The provider may
select typed operations and supply user-facing rationale, but it cannot supply
raw source text, patches, paths to write, shell commands, or validation
overrides.

Deterministic slash commands remain available without a provider. Offline
natural-language questions retain the existing deterministic ownership,
lineage, dependency, and model-summary behavior. A request that requires richer
reasoning fails with configuration guidance instead of pretending it was
understood.

### 4.2 Workspace editor

A provider-independent `WorkspaceEditor` accepts typed operations and owns the
safe editing lifecycle:

1. Resolve logical references to definitions and source files.
2. Copy the loaded workspace into a staged, in-memory representation.
3. Apply all operations to the staged representation.
4. Render every changed source file.
5. Parse and validate the complete staged workspace.
6. Calculate compatibility and downstream impact.
7. Produce a pending change set with explanations and unified diffs.
8. On confirmation, verify source fingerprints and revalidate.
9. Commit all staged files with rollback protection.
10. Reload the workspace and report the resulting references.

The editor is a Python application service above existing compiler modules. It
does not duplicate grammar, validation, compatibility, or lineage rules.

### 4.3 Conversation service

The conversation service coordinates messages, plans, editor results, and
confirmation. `modelable chat` becomes a thin CLI adapter over this service.
The service has no Click dependency so the language server can expose it
through future custom requests.

## 5. Typed Plans and Operations

The plan schema is closed and versioned. The first operation vocabulary covers:

- `CreateModel`
- `CreateProjection`
- `AppendModelVersion`
- `AppendProjectionVersion`
- `AddField`
- `RenameField`
- `RemoveField`
- `ChangeFieldType`
- `SetFieldOptionality`
- `SetFieldAnnotations`
- `SetPrimaryIndex`
- `AddSecondaryIndex`
- `RemoveSecondaryIndex`
- `SetProjectionSource`
- `AddProjectionField`
- `SetProjectionMapping`
- `AddProjectionJoin`
- `SetProjectionFilter`
- `SetProjectionGrouping`
- `RenameDefinition`
- `RetireDefinition`

Each operation identifies a logical target and contains only semantic values.
It never names a filesystem destination. The editor resolves file ownership
from the loaded workspace.

The operation vocabulary may grow as compiler surfaces become safely editable,
but unknown operation kinds always fail closed.

## 6. Complete Definition Synthesis

Whole-definition creation is a first-class planner capability. A short request
may omit mechanical details that can be safely proposed in a preview. For
example:

```text
add a customer entity with address
```

may produce a version 1 entity with:

- a conventional UUID key;
- customer identity and display fields inferred from the prompt;
- structured address fields such as street, city, postal code, and country;
- the owner inherited from an explicitly selected domain; and
- an additive initial change classification.

Every inference appears in the assumptions section of the preview. The user can
refine the pending proposal conversationally before applying it.

The planner asks a clarification question instead of inferring when ambiguity
changes:

- the owning domain or team;
- the model kind or identity boundary;
- whether a concept such as `Address` is an inline structure, a reusable record,
  or a separately owned entity;
- which existing version or similarly named definition is intended; or
- a projection's source contract.

## 7. Version and Draft Semantics

Existing versioned contracts are immutable by default. A request to update an
existing model or projection produces the next available version, carries
forward unchanged structure, and classifies the result as additive or breaking
using the existing compatibility engine.

In-place edits require an explicit draft-edit instruction. The preview must
label the operation as an in-place draft edit and warn that Modelable cannot
infer publication state from a local source file. An implicit mutation never
rewrites an existing version.

Renaming or retiring a published definition is represented through a new
version or replacement definition where the language supports it. If the
requested lifecycle cannot be expressed safely in current `.mdl` semantics,
the planner returns an unsupported result with the required manual decision.

## 8. Pending Change Sets and Confirmation

Only one pending change set exists in a chat session. It contains:

- a unique change-set ID;
- the typed plan;
- inferred assumptions;
- rendered candidate files;
- a source fingerprint for every read file;
- directly changed definitions;
- affected downstream definitions and the dependency reason;
- compatibility and validation findings;
- textual unified diffs; and
- the focused reference to use after application.

Read-only questions do not discard the pending change set. A new mutation
request replaces it only after telling the user that the previous proposal is
being superseded. `/discard` clears it.

Natural-language confirmation such as "apply" and the explicit `/apply`
command both target only the currently displayed change-set ID. Confirmation
does not authorize a regenerated or silently repaired plan.

Before writing, the editor:

1. recomputes every source fingerprint;
2. rejects the operation if any relevant file changed;
3. rebuilds and validates the staged workspace; and
4. verifies that the resulting files and findings match the confirmed change
   set.

## 9. Multi-File Write Safety

The editor stages all rendered files before modifying the workspace. It then
uses same-directory temporary files and preserves the original bytes needed
for rollback.

If preparation, replacement, or post-write reload fails, the editor restores
every file already replaced and reports the failure. A successful result is
reported only after all files are replaced and the workspace reloads
successfully.

This is rollback-protected application rather than a claim of operating-system
transactionality across files. Process termination or machine failure during
replacement may still require recovery. Temporary and recovery artifacts must
be named deterministically enough for Modelable to diagnose and clean up on the
next run.

## 10. Textual Interaction

Read-only answers cite concrete Modelable references and distinguish workspace
facts from recommendations.

A mutation preview is rendered in this order:

1. Summary
2. Inferred assumptions
3. Proposed definitions and operations
4. Directly changed entities and projections
5. Downstream affected entities and projections, with reasons
6. Compatibility and validation findings
7. Unified diffs grouped by source file
8. Confirmation instructions and change-set ID

The output remains plain text and suitable for terminals, tests, logs, and a
future editor text view. A future UI may render the same typed result visually
without changing planner or editor semantics.

After successful application, chat reports:

- written paths;
- created or updated references;
- compatibility classification;
- validation status; and
- the new focused reference.

The conversation reloads its workspace context after the write so subsequent
answers cannot use the stale pre-application summary.

## 11. Error Handling

- Ambiguous ownership, identity, version, or projection source returns a
  clarification plan and stages nothing.
- Unknown references and unsupported operations fail before rendering.
- Provider output that remains invalid after one repair attempt stages nothing.
- Parse, semantic, compatibility, or dependency-analysis failures are shown in
  the preview or error response and block application.
- A stale source fingerprint invalidates the pending change set and requires a
  fresh preview.
- A write or reload failure triggers rollback and reports affected paths.
- An operational request outside this slice explains the boundary and points
  to the roadmap follow-up.

No failure path may claim that files were written unless the post-write
workspace reload succeeded.

## 12. Reuse by VS Code

The initial implementation adds no VS Code UI. It establishes the reusable
boundary needed by one:

- typed query, clarification, unsupported, and change-set results;
- provider-independent workspace editing;
- stable textual rendering;
- explicit preview, apply, and discard operations; and
- serializable diagnostics and affected-definition data.

A follow-up can expose these services through language-server requests. The VS
Code extension remains a thin client that renders conversation state and diffs;
it must not reimplement `.mdl` editing or validation in TypeScript.

## 13. Testing Strategy

### 13.1 Editor tests

- Create a complete entity with inferred fields.
- Create a projection with direct and computed mappings.
- Append additive and breaking model versions.
- Append projection versions and calculate affected dependents.
- Edit fields, annotations, indexes, sources, joins, filters, and grouping.
- Stage and validate changes spanning multiple source files.
- Reject stale source fingerprints.
- Roll back replacements when a later file write fails.
- Reload the workspace after a successful application.

### 13.2 Planner tests

- Parse each supported typed operation from a provider response.
- Reject raw patches, paths, unknown operations, and mismatched targets.
- Repair one malformed structured response.
- Ask for clarification on ownership, identity, reusable nested definitions,
  version ambiguity, and projection sources.
- Produce an unsupported plan for operational actions.
- Preserve deterministic offline reads and slash commands.

### 13.3 Interaction tests

- Ask about ownership, lineage, indexes, compatibility, and dependents.
- Preview "add a customer entity with address" with explicit assumptions.
- Refine a pending proposal before application.
- Apply the exact displayed change set using natural language and `/apply`.
- Discard a proposal.
- Preserve a pending change set while answering a read-only question.
- Replace a pending proposal only with an explicit warning.
- Render affected definitions and unified diffs in stable order.
- Keep files unchanged after every failed or unconfirmed path.

### 13.4 Regression tests

Existing `ask`, `chat`, `update`, and provider-integration tests remain green.
The current direct `update` command keeps its public behavior until it is
migrated onto `WorkspaceEditor` in a deliberate compatibility-preserving
follow-up or implementation step.

## 14. Documentation and Roadmap

Implementation must update:

- `docs/cli-reference.md` with conversational query, preview, refinement,
  `/apply`, and `/discard` behavior;
- `docs/architecture.md` with the reusable editor boundary;
- provider and configuration documentation if planner requirements change;
- `CHANGELOG.md` with user-visible behavior; and
- `ROADMAP.md` as delivery stages ship.

The [roadmap](../../../ROADMAP.md) must retain explicit follow-ups for:

1. VS Code chat/editor integration through language-server requests.
2. Conversational compilation, registry synchronization, publishing, and
   external-service management with separate authorization and confirmation
   policies.

The execution sequence is defined in the
[Conversational Workspace Management Implementation Plan](../plans/2026-07-18-conversational-workspace-management.md).

No ADR change is required for this design because it preserves the existing
compiler authority and local-first architecture. It introduces an application
service over documented parser, validation, compatibility, and language-server
boundaries rather than changing those architectural decisions.

## 15. Acceptance Criteria

The slice is complete when a user can:

1. ask a natural-language question grounded in the current workspace;
2. request a complete new entity or projection, or revise an existing
   definition;
3. receive a validated, compatibility-aware multi-file preview containing
   assumptions, affected definitions, and textual unified diffs;
4. refine or discard the proposal without changing source files;
5. explicitly apply the exact previewed change set;
6. receive a successful post-write reload result with updated references; and
7. continue the conversation against the updated workspace.

The same editor behavior must be testable without a model provider and callable
without importing Click or VS Code-specific code.
