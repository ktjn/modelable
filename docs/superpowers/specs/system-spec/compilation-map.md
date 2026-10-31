# Compilation dependency, ownership and side-effect map

- Discovery revision: `3379c7c633f8b2690a4668cdb57abb5a07b9029d` (merged PR #893). Runtime characterization remains pinned to `8de5b55bf07cff4a619c6ae25f2c3368290d310b`; compilation Python sources are unchanged between these revisions.
- Authority: existing source, [architecture](../../../architecture.md), planner/registry protocols and native gates. This is a bounded observed map; whole-product ownership and release acceptance remain open.
- Source inventory: [compilation-discovery.json](compilation-discovery.json), [import closure](evidence/compilation-imports.tsv), [19 declared dataclass shapes](evidence/compilation-types.json).
- Static closure covers 141 internal modules, including guarded/function-local imports and package initializers; no unresolved internal module imports were found by this scan. It is not a runtime call graph or proof that every branch executes. Dynamic loading, dependency internals and shared IR semantics need separate review.

## Boundary and providers

The compilation unit coordinates one staging/promotion/freshness boundary. Provider names below identify real modules or local tools, not new deployed services. The five modeled top-level DTOs and their existing context-budget override stay unchanged; nested implementation records are documented here rather than split into fictitious components.

| Provider / source authority | Compilation dependency | State / boundary |
|---|---|---|
| [compilation.py](../../../../cli/src/modelable/operations/compilation.py#L257) | `CompilationService.execute_direct/preview/apply/discard` | Owns invocation staging, confirmation/freshness binding and local promotion orchestration. Caller owns source workspace and requested destinations. |
| [compiler/workspace.py](../../../../cli/src/modelable/compiler/workspace.py), `parser/ir.py`, validation/facets | `load_workspace`, `Workspace`, `MdlFile`, diagnostics | Shared semantic authority; compiler IR/facet internals remain with their existing definitions. Compilation reads them and does not become their sole schema owner. |
| [config.py](../../../../cli/src/modelable/config.py), `overlays` | `load_config`, `OverlayDocument`, overlay admission | Workspace input authority: explicit overlay, configured target overlay or conventional `modelable.extensions/<target>.toml`. Existing `modelable.toml` is fingerprinted when configuration selects the overlay. |
| [registry/ids.py](../../../../cli/src/modelable/registry/ids.py), `enum_numbers.py` | Allocation/read/write functions and `RegistryIdLock` | Registry modules define ledger formats and lock behavior; compilation stages and publishes the resulting files. Adjacent `.<ledger-name>.lock` files serialize ledger updates. |
| [registry/snapshot.py](../../../../cli/src/modelable/registry/snapshot.py), resolver/index/local/factory | Offline snapshot loading, extension pins, registry build and local publication | Read supplied snapshot / registry-lock state; build SQLite registry in staging. `LocalRegistry` publishes the staged index through the current local path behavior. |
| [planner/plans.py](../../../../cli/src/modelable/planner/plans.py), [protocol.py](../../../../cli/src/modelable/planner/protocol.py#L18) | `write_plans`, `PLAN_V1_SCHEMA` | Planner owns `modelable.plan/v1`; compilation promotes generated plan files. Plan internals are not invented as new DTO fields here. |
| [emitters/base.py](../../../../cli/src/modelable/emitters/base.py), target emitters, `extensions.py` | `EmittedArtifact`, target admission and rendering | Emitter-owned content contract (`dict`, text or bytes); compilation owns the lifetime and destination mapping of staged instances. Target-dependent extension and package checks remain authoritative. |
| [artifact_manifest.py](../../../../cli/src/modelable/artifact_manifest.py), `registry/usage_protocol.py` | Artifact manifest and optional usage manifest writers | `modelable-artifact-manifest.json` and optional `modelable-usage-manifest.json` are staged outputs. Usage protocol is `modelable.usage/v0`. |
| [llm/workspace_editor.py](../../../../cli/src/modelable/llm/workspace_editor.py#L98) | `AffectedDefinition` payload record | Physical import coupling to the editor module; no LLM-provider invocation occurs here. Shared DTO authority must be reviewed before extraction rather than treating the type import as an assistant-service dependency. |
| [file_transaction.py](../../../../cli/src/modelable/operations/file_transaction.py#L85) | `FileTransaction.promote`, `StagedFile`, rollback/committed-error records | Owns the workspace promotion lock, adjacent temp/backup files, ordered replacements, verification and compensation. It is part of the compilation consistency boundary. |
| [compilation_audit.py](../../../../cli/src/modelable/operations/compilation_audit.py) | `CompilationAuditRecord.to_bytes` | Compilation audit JSON is promoted with the confirmed outputs. Audit schema version 1 is distinct from Python dataclass field spelling. |
| [emitters/descriptors.py](../../../../cli/src/modelable/emitters/descriptors.py) / local `protoc` | Descriptor subprocess for protobuf/gRPC | External tool boundary: resolves `protoc` from PATH, runs in staged proto output and reads descriptor bytes. The symlink rerun does not exercise or establish a protoc version. |
| [registry/oci.py](../../../../cli/src/modelable/registry/oci.py) | `OCIRegistry` stub | Preview rejects OCI paths; direct compilation surfaces the adapter's unsupported-operation error. `push` and `pull` raise `OCIRegistryError`; no live OCI transfer is implemented or claimed. Apicurio publishing is a different product command boundary. |

The static scan reaches `jsonschema`, `lark`, `openapi_spec_validator`, `pydantic`, `searchable` and `yaml` modules. Exact dependency versions remain in `cli/uv.lock` and capture environments; this list is not the complete installed-package inventory.

## Nested records and state ownership

[compilation-types.json](evidence/compilation-types.json) retains declared annotations and source lines for nineteen dataclasses. It expands the five original DTOs plus the following records; annotations are not executable wire schemas and omit computed properties.

| Record family | Definition authority | Instance lifetime / state owner |
|---|---|---|
| `CompilationPolicy` | Compilation module | Preview caller supplies the workspace-restriction policy. `conversation()` also sets `write_audit`; apply's audit construction is explicit in the operation, not a separate policy-driven service. |
| `FileFingerprint` | Compilation module | Pending invocation holds path/content hash/size/resolved-parent observations used during apply freshness checks. |
| `CompilationFilePreview` | Compilation module | Pending/applied results hold category, destination/stage paths, status, before/after hashes/sizes/text, diff, media type, ref and resolved parent. These describe source-derived user data; restricted handling remains provisional. |
| `RegistryIdChange` / `CompilationEvent` | Compilation module | Invocation-local allocation/event metadata, exposed through pending/direct results. |
| `AffectedDefinition` | Workspace editor module | Shared shape; compilation constructs its own affected-definition tuple. Definition location does not assign all instances to the editor or imply a model-provider call. |
| `StagedFile` / `RollbackError` | File-transaction module | Promotion input and local failure/cleanup detail. `Exception` in `RollbackError` is an in-process object, not a JSON wire type. |
| `CompilationAuditDestination` / `CompilationAuditRecord` | Compilation audit module | Durable audit payload owned by compilation's apply transaction. `to_dict()` emits camelCase keys and nested confirmation/plan/destination records; `to_bytes()` emits sorted compact UTF-8 JSON plus newline. |
| `EmittedArtifact` | Emitter base module | Shared emitter contract; staged instances become bytes before promotion. |
| `WorkspaceSource` / `Workspace` / `Diagnostic` | Compiler/diagnostics modules | Shared read/analysis structures. `MdlFile`, facets, diagnostic enum and other nested IR internals retain their existing source authorities; they are explicit semantic-review boundaries beyond these nineteen shapes. |

`PendingCompilation.audit_path` is computed from workspace root/action ID. It is not an additional stored dataclass field. Private `_PreviewLayout`, `_DirectPathMapper`, `_CompilationRunResult` and `_Promotion` remain implementation-local helpers, not independent state owners.

## Local operation protocol

| State / operation | Inputs, permissions and locks | Durable effects / success | Failure and recovery |
|---|---|---|---|
| No pending work -> direct | Caller filesystem permissions; registry-ID lock then enum-number lock; target/package/extension checks | Stage local registry, ledgers, plans and generated artifacts; `FileTransaction` takes the workspace lock and promotes mapped destinations. Direct execution writes no conversational audit. | Precommit errors remove staging. Lock/contention and filesystem exceptions still require complete public-surface error review. There is no remote OCI commit to roll back because OCI publication is unsupported. |
| No pending work -> preview | Workspace-restricted policy, local supported paths; source/config/overlay fingerprints | Builds outside the workspace and returns previews, staged hashes and a manifest binding. No destination promotion. | Path/overlap/unsupported-target checks reject the request; cleanup errors are surfaced. Snapshot/IR/dependency freshness beyond the explicitly fingerprinted inputs remains a review boundary. |
| Pending -> apply | Exact action ID and manifest confirmation; registry-ID lock; source/destination/stage/manifest and audit-parent checks | Stage audit; workspace promotion lock; recheck freshness under the lock and before replacing files; promote confirmed bytes without recompiling. Success returns written paths and audit path. | Stale confirmation/input rejects apply. Promotion errors attempt compensation and report every rollback error. Partial rollback must not be described as guaranteed original state. |
| Pending -> discard | Caller-owned pending invocation | Remove staging; repeated discard is idempotent | Incomplete cleanup is surfaced; discard never means the staged output was applied. |
| Promotion committed -> cleanup | All replacements and destination hash checks completed | Committed destination bytes remain in place even if backup/staging/lock cleanup fails | `FileTransactionCommittedError` distinguishes committed writes and cleanup errors. Preserve this outcome; do not interpret every failing return as no writes. |

Direct and conversational policies differ. Direct path mapping preserves the existing last-writer behavior when requested destinations resolve to the same path; preview rejects overlapping control/output paths. Do not infer identical guarantees from shared helper use.

## Promotion, locking and exceptional side effects

- Registry-ID and enum-number ledgers use the registry lock helper. Direct execution holds both ledger locks; apply holds the registry-ID lock and validates its before-state. The workspace promotion lock is `.modelable/locks/compilation.lock`, with waiter/PID liveness handling in `FileTransaction`.
- Promotion verifies staged hashes, prepares adjacent temporary/backup files, revalidates, replaces destinations, verifies final hashes, then disposes backups and releases locks. A destination collision uses `_last_writers` by resolved path identity.
- Compensation restores backups/removes newly written files where possible. Errors and preserved backups are reported. Cleanup can leave quarantined `.modelable-cleanup-*` files or released-lock artifacts; they are operational recovery state, not accepted product output.
- These are multiple per-file replacements with compensation. No durable multi-file commit journal or crash-atomicity proof is asserted. PID-based stale-lock reclamation is observed behavior, not formal assurance against every crash/race scenario.
- `LockContentionError` and `RegistryIdLockContentionError`, plus lower-level filesystem failures, can cross helper boundaries beyond the short service exception list in the original specification. Complete adapter translation/error-catalog review remains under MOD-COMP-09; this map does not silently redefine the frozen contract or claim those cases are covered by the original characterization record.
- Formal applicability remains open for lock ordering, freshness under contention, rollback and crash windows. Existing unit tests are supporting behavior evidence; this source map is not a proof.

## Symlink coverage decision

- Both missing cases ran against the original runtime revision `8de5b55b` under CPython 3.14.5 / pytest 9.1.1 on a Linux container filesystem: **2 passed, 0 skipped**. Source archive, image digest/ID, locked packages and exact command are captured in [symlink-linux-environment.json](evidence/symlink-linux-environment.json).
- [JUnit](evidence/symlink-linux.xml), [output](evidence/symlink-linux.txt), [container recipe](evidence/symlink-linux.Dockerfile) and [runner](evidence/symlink-linux-run.py) are retained. The runner requires exactly two successful tests with no errors/failures/skips; tests and assertions are unchanged.
- The runtime container had networking disabled, a read-only root, tmpfs test state and only a fresh host result-directory mount. No Windows privileges were changed.
- Linux input uses exact Git-archive bytes (LF). Existing source bindings hash exact Windows checkout bytes (including CRLF). These conventions are recorded separately; Git/source correspondence is reviewed rather than pretending different byte hashes are equal.
- New evidence supersedes only the historical MOD-COMP-10 partial record. The original Windows skips remain visible in history; this closes the suitable-host execution requirement, not Windows symlink support or universal filesystem/security conformance.

To reproduce, create a fresh temporary build context, extract `git -c core.autocrlf=false -c core.eol=lf archive 8de5b55bf07cff4a619c6ae25f2c3368290d310b cli docs` into `source/`, copy the retained recipe as `Dockerfile` and runner as `run-checks.py`, then build locally. Run the resulting image with `--rm --network none --read-only --tmpfs /tmp` and an empty result-directory mount at `/results`. The recipe pins the Python base digest and uses `uv sync --frozen --extra dev`; never mount a valuable directory as pytest temp state.

## Decision and next handoff

- Archive the merged [migration plan](../../plans/archived/system-spec-evidence-migration.md); the ongoing onboarding specification stays active.
- Accept this bounded observed dependency/state map and the suitable-host execution of MOD-COMP-10 as supporting evidence. Preserve the original capability/data contracts and the existing category waiver.
- Keep whole-product architecture/release open. MOD-COMP-09 still owns measured performance/scalability/observability requirements, complete public error/failure review, transitive IR/schema semantics and formal applicability. Provisional classification review is also open.
- Next bounded review: reconcile the public error catalog and lock/compensation obligations, then map shared registry protocols and browser persistence against their existing authorities. Maintainers own acceptance and remediation scheduling.
