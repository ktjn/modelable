# Conversational Compilation Management — Design

Date: 2026-07-19

## 1. Purpose

Modelable's conversational workspace management can answer grounded questions
and safely preview and apply source changes. Compilation remains intentionally
unsupported because the current `modelable compile` command writes several
classes of local state directly:

- generated target artifacts;
- `registry-ids.lock`;
- the local registry database;
- `.modelable/plans`; and
- optional Protobuf or gRPC descriptor binaries.

This design adds compilation as the first conversational operational action. A
user can ask Modelable to compile a workspace, inspect the exact staged result
and affected definitions, and explicitly apply or discard it. The model may
propose a closed typed request, but it cannot execute a command, authorize a
write, select a remote service, or bypass validation.

The implementation establishes an operational-action pattern that later
registry synchronization and publishing designs may reuse. Those remote actions
remain outside this slice because their credential, network, and authorization
boundaries differ materially from local compilation.

## 2. Goals

The first slice must:

- support natural-language requests such as "compile this workspace to Rust"
  through the CLI chat and native VS Code `@modelable` participant;
- retain a deterministic `/compile` command when no LLM provider is configured;
- represent compilation with a closed, schema-validated plan;
- move compilation orchestration out of Click into a reusable Python
  application service;
- preserve the output and error behavior of the existing direct
  `modelable compile` command;
- stage the real compilation without changing the workspace;
- preview exact created, changed, and unchanged files in deterministic order;
- show full unified diffs for text outputs and size plus SHA-256 changes for
  binary outputs;
- explain which domains, entities, projections, and semantic types contribute
  to the result;
- include registry-ID ledger, local registry, plan, artifact, and descriptor
  effects in one pending action;
- require an explicit confirmation bound to the exact pending action;
- reject stale source or destination state before applying;
- promote the exact staged bytes without recompiling;
- roll back every promoted file if any write or audit step fails; and
- persist a privacy-preserving audit record for every successfully applied
  conversational compilation.

## 3. Non-Goals

This slice does not:

- publish artifacts or contracts;
- synchronize Apicurio, Marquez, OpenMetadata, OCI, or another external
  service;
- accept credentials, URLs, remote registry paths, or arbitrary environment
  variables from the planner;
- execute shell commands supplied by a model;
- support arbitrary compiler plugins;
- edit `.mdl` source files;
- delete stale or unrelated files from an output directory;
- add continuous or automatic compilation;
- add WebLLM or the VS Code Language Model API provider adapter;
- change compiler, emitter, registry-ID, or compatibility semantics; or
- make a conversational confirmation reusable across multiple operations.

Remote registry synchronization and publishing require separate designs with
operation-specific authorization and credential policies.

## 4. Existing Behavior and Constraints

`modelable compile` currently owns both Click argument handling and
orchestration. It:

1. loads and validates the workspace;
2. applies optional domain scoping;
3. allocates and writes registry IDs;
4. builds and writes the local registry database;
5. writes `.modelable/plans`;
6. emits the selected target;
7. optionally invokes local `protoc` for descriptor artifacts; and
8. writes generated artifacts sequentially.

Emitters already return `EmittedArtifact` values with paths, content, hashes,
warnings, and logical references. Those values are the correct basis for a
structured preview, but registry, plan, and descriptor writes must be captured
as well.

The current command does not remove files that are absent from a later compile.
The application service must preserve that behavior. Output cleanup or a
generated-file ownership manifest is deferred.

The existing conversation service permits one pending source change set and
uses `/apply` and `/discard` as explicit lifecycle commands. The language-server
protocol exposes the same lifecycle to VS Code. Compilation extends that
boundary rather than adding a parallel chat implementation.

## 5. Architecture

The dependency direction becomes:

```text
direct CLI compile       CLI chat       VS Code @modelable
         \                  |                  /
          \          conversation service    /
           \                |                /
            ->       CompilationService     <-
                       |          |
                 compiler/emitters   registry/plans/descriptors
```

### 5.1 Compilation service

Add a Click-independent `CompilationService` in the Python application layer.
It accepts a trusted `CompilationRequest` and exposes:

- `preview(request, context) -> PendingCompilation`;
- `apply(pending, confirmation) -> AppliedCompilation`;
- `discard(pending) -> None`; and
- a direct execution entry point used by `modelable compile`.

The direct CLI translates Click values into `CompilationRequest`. The
conversation service translates a validated `CompilePlan` into the stricter
conversational subset of that request. Emitters and compiler modules do not
depend on conversations, providers, Click, or VS Code.

Successful direct compilation retains the same files, bytes, console results,
and supported options. Validation and generation failures retain their
user-facing diagnostics but become safer: staging prevents a failed direct
compile from leaving the ledger, registry, plans, or artifacts partially
updated.

### 5.2 Shared behavior without shared authority

The service shares compilation behavior, not caller authority:

- direct `modelable compile` remains an explicitly invoked trusted command and
  does not require a conversational confirmation;
- conversational preview may stage local work but cannot change workspace
  files;
- conversational apply requires an exact pending-action ID and freshness
  verification; and
- only conversational apply writes the operational audit record introduced by
  this design.

### 5.3 Pending action lifecycle

Generalize the conversation session's pending value to a closed union:

- `PendingChangeSet`; or
- `PendingCompilation`.

There is still only one pending action per session. A new preview explicitly
replaces and disposes the previous pending action. `/apply`, `/discard`, session
expiry, explicit close, and process shutdown clean up compilation staging.

## 6. Typed Requests

### 6.1 Planner plan

Add `CompilePlan` to the discriminated `ConversationPlan` union:

```json
{
  "kind": "compile",
  "target": "rust",
  "domains": ["customer"],
  "output": null,
  "descriptor_set": false,
  "summary": "Compile the customer domain to Rust."
}
```

The schema is closed. It permits only:

- a currently implemented target;
- zero or more existing domain names;
- an optional normalized workspace-relative output directory;
- `descriptor_set: true` only for Protobuf or gRPC; and
- a user-facing summary.

The planner cannot set:

- the workspace source path;
- registry database or registry-ID ledger paths;
- `allow_orphaned_registry_ids`;
- an absolute path or parent traversal;
- a URL or remote registry;
- a command, executable, environment variable, or compiler flag; or
- a validation or freshness override.

The conversation session supplies the saved workspace root. Registry state uses
the local defaults `.modelable/registry.db` and `registry-ids.lock`.
Orphaned-ledger failures require the user to resolve the ledger or invoke the
direct CLI deliberately; the model cannot enable the override.

### 6.2 Deterministic command

Support:

```text
/compile <target> [--domain <name> ...] [--out <relative-path>] [--descriptor-set]
```

This command uses the same parser and plan validation without invoking an LLM.
Unknown options, duplicate incompatible options, invalid domains, and
descriptor flags on other targets fail before staging.

Natural-language requests require a configured provider and produce the same
typed plan. A provider response that attempts an unsupported operational action
remains an `UnsupportedPlan`.

### 6.3 Service request

`CompilationRequest` also supports the existing trusted direct-CLI options so
the Click command can retain its public interface. Caller policy determines
which fields are legal. The conversation adapter constructs only the restricted
local subset above.

## 7. Path Policy

Conversational output paths must:

- be relative to the resolved workspace root;
- remain inside that root after normalization and symlink resolution;
- avoid `.git`, `.modelable/audit`, and internal staging or lock locations;
- not overlap any `.mdl` source file; and
- use the target's current default when omitted.

Every parent component is rechecked immediately before apply. A symlink or
directory replacement after preview invalidates the action.

The direct CLI retains its existing accepted path forms. Remote OCI behavior
continues to fail with the current explicit unsupported error; conversational
planning never creates such a request.

## 8. Staging

### 8.1 Isolation

Preview creates a private operating-system temporary directory outside the
workspace. It mirrors the intended destination layout and runs the real
compilation there:

1. load and validate the saved workspace;
2. validate domain scope and dependencies;
3. copy current local registry inputs needed for compilation;
4. allocate registry IDs in staging;
5. build the registry database in staging;
6. generate `.modelable/plans` in staging;
7. emit the selected target into staging; and
8. generate requested descriptors in staging with local `protoc`.

No destination directory, lock file, registry file, audit file, or generated
artifact is created or modified during preview.

### 8.2 Destination manifest

The pending compilation owns an immutable manifest containing:

- action ID and canonical plan;
- workspace source fingerprints;
- normalized destination paths and resolved parent paths;
- whether each destination existed;
- before and staged SHA-256 hashes and byte sizes;
- staged file location and media classification;
- file status: `created`, `changed`, or `unchanged`;
- warnings and diagnostics;
- affected definition references and reasons;
- registry-ID allocations added by the operation;
- tool requirements such as `protoc`; and
- a fingerprint of the complete manifest.

The service stores exact staged bytes. Apply never asks an emitter, registry
builder, or descriptor tool to run again.

### 8.3 Text and binary previews

UTF-8 text files include complete before and after text plus a unified diff.
Created files diff against an empty input. Unchanged files remain listed but do
not repeat their content.

Binary files, including the registry database and descriptor sets, show:

- logical purpose;
- path;
- before and after sizes;
- before and after SHA-256 hashes; and
- created, changed, or unchanged status.

To keep the protocol and terminal usable, the first slice accepts a pending
action only when its complete serialized text preview is at most 2 MiB. Larger
text previews fail safely with guidance to use direct `modelable compile`.
Binary bytes remain in staging and do not count toward that text limit.

### 8.4 Affected definitions

The preview distinguishes generated effects from source changes. It explicitly
states that source definitions are not modified and reports:

- domains selected for compilation;
- entities, projections, and semantic types consumed by the target;
- the logical reference associated with each emitted artifact;
- semantic declarations receiving new registry IDs; and
- cross-domain dependencies required by the selected scope.

References are sorted canonically and use existing definition-location lookup
so VS Code can render source anchors.

## 9. Confirmation and Freshness

Only the literal `/apply` command or the native VS Code Apply action may
authorize a pending compilation. Existing conversational aliases such as
`apply`, `apply it`, or `confirm` remain compatible for source-edit change sets
but return `/apply` guidance while a compilation is pending. Natural-language
phrases inside a provider response never authorize an operation.

The confirmation is bound to:

- session ID;
- pending action ID;
- manifest fingerprint; and
- the current protocol version.

Immediately before writing, the service rechecks:

- every `.mdl` source fingerprint;
- every destination's existence, bytes, and resolved parent path;
- registry ledger and database inputs;
- output-directory symlinks;
- the pending staging manifest; and
- that the action is still the session's current pending action.

Any mismatch returns a stale-preview error, disposes the staged result, and
requires a new preview. The service does not merge or overwrite concurrent
changes.

VS Code already requires saved `.mdl` documents before conversation work. For
compilation apply, the extension also reports dirty open documents that match a
planned destination; apply refuses until those files are saved or closed.

## 10. Promotion and Rollback

Apply uses one workspace-scoped compilation lock to prevent concurrent
promotions. After freshness checks:

1. copy each staged file to a temporary sibling of its destination;
2. retain backups of every existing destination;
3. atomically replace individual destination files in deterministic order;
4. write the audit record as the final member of the transaction;
5. reload and verify the resulting hashes; and
6. release backups and staging only after all checks pass.

If any copy, replacement, audit, or verification step fails, the service
restores every prior file, removes files created by the failed apply, removes
empty directories it created, and reports the rollback result. Rollback errors
are surfaced individually and never hidden behind the original failure.

This is transaction-like multi-file behavior built from atomic file
replacement and rollback. The design does not claim that a filesystem provides
a single atomic primitive across all paths.

Unmentioned destination files are never removed.

## 11. Audit Policy

Each successful conversational apply writes:

```text
.modelable/audit/compilations/<action-id>.json
```

The versioned record contains:

- audit schema version;
- action and session IDs;
- preview and confirmation timestamps;
- confirmation surface (`cli-chat` or `vscode-chat`);
- configured provider and model identity when available;
- canonical compile plan;
- affected definition references;
- destination statuses, paths, sizes, and hashes;
- registry-ID allocations;
- warnings;
- manifest fingerprint; and
- final outcome.

It excludes:

- prompt and response text;
- source and artifact contents;
- tokens and credentials;
- environment variables;
- unrelated file names; and
- provider request metadata.

Audit writing participates in rollback. If the record cannot be persisted and
verified, the compilation is not reported as applied. Direct
`modelable compile` preserves its existing behavior and does not create this
conversational audit record.

## 12. Conversation and Protocol Behavior

### 12.1 Reply shape

Compilation previews retain the existing human-readable `text` summary and add
structured operational fields:

- operation kind and plan;
- affected definitions;
- file manifest;
- textual preview files;
- registry-ID changes;
- warnings and diagnostics; and
- audit destination.

Existing source-change fields remain available. The protocol version increments
because the pending action and preview schema expand. Python and the bundled VS
Code extension update together and continue to fail clearly on a mismatched
protocol version.

The existing opaque `changeSetId` remains the confirmation token in this slice
to avoid an unnecessary public rename. Its documented meaning broadens to
"pending action ID."

### 12.2 CLI rendering

CLI chat renders:

1. summary and normalized plan;
2. affected definitions and source anchors;
3. target, domains, output, and descriptor requirements;
4. created, changed, and unchanged files;
5. registry-ID changes;
6. full textual diffs;
7. binary size and hash changes;
8. warnings and diagnostics; and
9. the exact `/apply` and `/discard` choices.

An applied reply lists written paths, hashes, affected definitions, and the
audit record.

### 12.3 VS Code rendering

The extension remains a presentation-only client:

- Markdown renders the shared explanation and file manifest;
- definition references link to source locations;
- each changed or created text file can open in the built-in diff editor using
  exact before and staged snapshots;
- binary entries render size and hash changes without attempting a text diff;
- Apply and Discard use the existing native follow-up flow; and
- TypeScript never parses plans, invokes emitters, or writes generated files.

## 13. Error Handling

Failures before a complete manifest produce an error reply and no applicable
pending action. This includes:

- invalid or ambiguous planner output;
- unsupported target or option combinations;
- unknown domains or excluded dependencies;
- workspace parse, semantic, or governance errors that block compilation;
- orphaned registry-ID ledger entries;
- output path or symlink violations;
- unavailable `protoc`;
- emitter, registry, or plan generation failure;
- staging disk exhaustion;
- preview payload above the text limit; and
- staging cleanup failure.

Apply-specific failures include:

- expired, replaced, discarded, or foreign action IDs;
- dirty source or destination documents;
- source, destination, ledger, registry, or path staleness;
- lock contention;
- write or verification errors; and
- audit persistence failure.

Errors identify the failed phase and safe next action without exposing source
or artifact contents.

## 14. Security and Privacy

- The planner selects values from a closed schema and never supplies executable
  code.
- Compilation remains local and makes no network request.
- Output and registry paths are application-resolved and revalidated.
- `protoc` is invoked only through the existing descriptor API with staged,
  application-generated paths.
- Imported source and generated content remain untrusted text or bytes.
- Preview and audit rendering escapes terminal and Markdown control content.
- Staging permissions are private to the current user.
- Staging is deleted on discard, expiry, replacement, close, successful apply,
  and recoverable failure.
- Audit records contain hashes and identifiers, not model content or prompts.

No ADR change is required. This design preserves compiler authority, local-first
execution, provider-independent application services, and the existing
language-server boundary. It adds an application service and an explicit
authorization lifecycle within those decisions.

## 15. Testing Strategy

Implementation follows test-driven development.

### 15.1 Compilation-service parity

Contract fixtures compare the direct CLI before and after extraction across:

- every implemented target;
- default and explicit output paths;
- whole-workspace and domain-scoped compilation;
- registry-ID allocation;
- local registry and plan generation;
- Protobuf and gRPC descriptors;
- warnings and empty artifact sets; and
- current failure messages.

### 15.2 Preview and apply

Tests prove:

- preview leaves the workspace byte-for-byte unchanged;
- created, changed, and unchanged text files are classified and diffed
  correctly;
- binary hashes and sizes are accurate;
- affected definition explanations are complete and deterministic;
- apply writes exactly the staged bytes without recompiling;
- unmentioned files remain untouched;
- discard and lifecycle cleanup remove staging;
- source, destination, registry, ledger, and symlink changes invalidate apply;
- action IDs cannot cross sessions;
- dirty VS Code destinations block apply;
- every injected promotion failure restores the original filesystem;
- audit failure rolls back compilation; and
- successful apply writes a schema-valid, privacy-preserving audit record.

### 15.3 Planner, protocol, and surfaces

Tests cover:

- schema acceptance and rejection for `CompilePlan`;
- deterministic `/compile` parsing without a provider;
- natural-language plan routing with a fake provider;
- unsupported remote or credential-bearing requests;
- session replacement, apply, discard, expiry, and close;
- versioned language-server serialization;
- VS Code Markdown, anchors, text diffs, binary summaries, and follow-ups; and
- an end-to-end flow from "compile this workspace to Rust" through exact
  preview, explicit apply, artifacts, registry state, and audit record.

### 15.4 Repository gates

Before every commit, run from `cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

For extension changes, also run from `vscode/`:

```bash
npm run check
npm run build
npm test
npm run package
```

Browser behavior is unchanged, but the final implementation runs the browser
surface-detection and regression gates when shared workflow or documentation
files are touched.

Documentation must pass strict MkDocs build and the four-phase documentation
review.

## 16. Documentation and Roadmap

Implementation updates:

- `docs/cli-reference.md` with `/compile`, natural-language compilation,
  preview, apply, discard, and audit behavior;
- `vscode/README.md` with compilation preview, generated-file diffs, dirty
  destination handling, and audit location;
- `docs/architecture.md` with the reusable compilation service and pending
  operational-action boundary;
- `docs/maintainers.md` with staging and audit troubleshooting;
- `CHANGELOG.md` with user-visible behavior; and
- `ROADMAP.md` to mark this first operational action shipped while retaining
  registry synchronization, publishing, and external-service operations as
  separate follow-ups.

After implementation merges, move this specification and its implementation
plan into their `archived/` directories in the same PR or a prompt follow-up.

## 17. Delivery Sequence

The implementation plan should stage work in this order:

1. characterize current CLI compilation behavior with contract tests;
2. extract and adopt `CompilationService` without changing direct CLI output;
3. add isolated staging, destination manifests, and previews;
4. add freshness, promotion, rollback, and audit behavior;
5. add typed planning and deterministic `/compile`;
6. generalize conversation sessions and the language-server protocol;
7. add CLI and VS Code presentation and confirmation flows; and
8. complete documentation, cross-surface regression, and archive bookkeeping.

Each step must leave the direct CLI and existing source-edit conversations
working.

## 18. Acceptance Criteria

The slice is complete when:

1. `modelable compile` uses the shared service without changing its supported
   targets, options, outputs, or errors;
2. a CLI or VS Code user can request a local compile in natural language or
   with `/compile`;
3. preview performs the real compile without changing the workspace;
4. preview lists exact files, full text diffs, binary hashes and sizes,
   registry-ID changes, and affected definitions;
5. no model output can authorize apply or introduce arbitrary paths, commands,
   credentials, URLs, or flags;
6. explicit confirmation applies the exact staged bytes without recompiling;
7. stale or dirty state is rejected without overwriting concurrent work;
8. any partial failure restores the original filesystem;
9. successful conversational apply writes the required audit record;
10. source-edit conversations remain behaviorally compatible;
11. CLI, language-server, VS Code, documentation, and relevant browser gates
    pass; and
12. registry synchronization, publishing, and external-service actions remain
    unsupported with clear roadmap guidance.
