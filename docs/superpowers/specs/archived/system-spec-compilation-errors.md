# Compilation error contracts and adapter outcomes

Historical completed review from PR #895. Current cleanup-outcome changes and renewed source evidence are in [compilation-recovery.md](../system-spec/compilation-recovery.md).

- Scope: the Python compilation service, CLI, shared filesystem conversation, LSP request/serialization layer and VS Code participant. Source/revision/file pins and actual results are in [error-boundary-characterization.json](../system-spec/evidence/error-boundary-characterization.json).
- Preserve the frozen [historical compilation contract](../system-spec/evidence/compilation-before-recovery.yaml), original source/evidence and the [dependency/ownership map](../system-spec/compilation-map.md). This review does not silently add failure modes or claim whole-product conformance.
- Implemented change: known CLI operational failures now use the existing Click error format with exit 1. A committed-cleanup error includes committed written paths and cleanup detail. Existing rich diagnostics and Python service exception types stay unchanged; unexpected programming faults propagate.

## Observed error families

| Python family / authority | Meaning and boundary | CLI translation |
|---|---|---|
| `CompilationDiagnosticsError` / [compilation.py](../../../../cli/src/modelable/operations/compilation.py) | Parse/workspace diagnostics; subclass of `CompilationError` with diagnostic records and origin | Existing rich diagnostic lines and exit 1 remain unchanged. |
| `CompilationError`, including `StaleCompilationError` | Domain/preflight/confirmation/freshness and staged-cleanup failures explicitly translated by service helpers | Existing `ClickException` presentation, exit 1. Staleness belongs to apply; the CLI direct command is not a conversation apply command. |
| `FileTransactionError` / [file_transaction.py](../../../../cli/src/modelable/operations/file_transaction.py) | Promotion failure with original cause and zero or more rollback errors. Compensation can itself be incomplete. | New explicit CLI translation preserves the full message and rollback details, exit 1. It does not claim guaranteed original state. |
| `FileTransactionCommittedError` | Replacements committed, post-commit cleanup incomplete; carries `written_paths`, `cleanup_errors`, and `committed = True` | New explicit CLI translation preserves committed wording, cleanup details and written paths, exit 1. It does not retry or mutate committed files. |
| `LockContentionError` / file transaction | Workspace promotion lock could not be acquired | New explicit CLI translation, exit 1. Python class identity remains unchanged. |
| `RegistryIdLockContentionError` / [registry/ids.py](../../../../cli/src/modelable/registry/ids.py) | Ledger lock timeout/contention | New explicit CLI translation, exit 1. Python class identity remains unchanged. |
| `OSError` subclasses | Filesystem operations outside transaction wrapping can fail during setup/staging/audit IO | New explicit CLI translation, exit 1. This is not a complete taxonomy of every dependency/programming failure. |
| Unexpected programming faults (regression uses `RuntimeError`) | Not reclassified as an expected operational error | Original exception propagates. No broad `except Exception` was added to the CLI command. |

Public helper lock/IO families exceed the short frozen version-1.0 service catalog. The table records observed boundaries; it does not redefine that baseline or prove every dependency fault is enumerated. Complete service-contract correction and consumer review remain under MOD-COMP-09.

## Adapter matrix: domain outcome is not surface status

| Adapter / source | Ordinary failure | Committed cleanup failure | Pending state / retries |
|---|---|---|---|
| Python `CompilationService` | Raises the applicable domain/helper/IO exception; staging cleanup may also fail | Raises the committed error with committed paths/cleanup details | Caller must distinguish commit, compensation and cleanup. Method exception types are unchanged by this CLI fix. |
| [CLI compile command](../../../../cli/src/modelable/commands/compile.py) | Known operational errors become actionable Click failures with exit 1; diagnostics keep their rich path | Exit 1 plus explicit committed outcome, written paths and cleanup details | One service invocation; no automatic retry or cleanup action in the error renderer. A nonzero exit is not proof of rollback. |
| [Filesystem conversation](../../../../cli/src/modelable/llm/filesystem_conversation.py) apply | Noncommitted exceptions become `ConversationReply(kind="error")`; staging existence determines whether the pending action is cleared or tracked for cleanup | Special handler returns `kind="applied"` with committed paths, audit path and cleanup-warning text; clears pending/cleanup backlog for that action | Error does not promise that the original action remains retryable. The stage may already have been removed. |
| Filesystem conversation preview/discard and [session facade](../../../../cli/src/modelable/llm/conversation.py) | Preview translates `CompilationError`; other unexpected exceptions can escape. Session cleanup preserves the primary exception and records cleanup notes. Discard/close track incomplete cleanup for retry. | Apply delegates to the committed-specific behavior above | Existing cleanup/backlog tests characterize retention and retry. No new conversation or model-provider behavior is introduced here. |
| [LSP service](../../../../cli/src/modelable/lsp/conversation_service.py), [request handlers](../../../../cli/src/modelable/lsp/server.py) | Saved-file/session/pending preconditions can raise before backend execution. Domain error replies are serialized as reply data; exceptions can leave the handler. | Serializes the backend's `applied` outcome and write/audit metadata | The exact transport fault code for every escaping exception is not established by this capture. Successful JSON-RPC round trips do not prove all error mappings. |
| [VS Code client](../../../../vscode/conversationClient.js) / [participant](../../../../vscode/conversationParticipant.js) | Renders returned reply text/metadata. Thrown request errors enter the participant's sanitized `errorDetails` path. | A returned `kind="applied"` is rendered as applied and removes that preview cache entry | Error replies can leave cached preview content. Cache retention alone does not establish server pending-state ownership or safe retry eligibility. |

The existing committed-conversation test checks `kind="applied"`, written paths, committed wording, cleanup-warning text and cleared pending state. Existing LSP tests include a real JSON-RPC preview/apply round trip. VS Code source and its native suite are supporting evidence; manual editor/model acceptance and every transport failure path are not claimed.

## Test-first remediation and bounded evidence

- Six new CLI cases cover promotion/rollback detail, workspace and ledger contention, filesystem IO, committed cleanup, and unexpected-fault propagation.
- Before implementation: **five failed, one passed** for the expected missing user-facing message. The unexpected-fault case already passed. [Original regression output](../system-spec/evidence/cli-errors-red.txt).
- After repair: the CLI subset passed **69 tests**. Wider service/CLI/conversation/LSP/protocol/real-JSON-RPC characterization passed **295 tests, 6 skipped**; exact source, command, environment and skip reasons are retained in the capture. [Output](../system-spec/evidence/error-boundaries.txt).
- Platform skips are explicit: two directory-symlink cases, three POSIX metadata cases and one LSP symlink case. The earlier suitable-host evidence for MOD-COMP-10 remains separate; these skips are not relabeled as passes.
- The immutable code commit is captured before the documentation/evidence commit. File hashes distinguish exact checkout bytes from Git blob bytes; the later native gate verifies the final delivery commit independently.

## Frozen-catalog compatibility decision

[Compatibility probe](../system-spec/evidence/error-compatibility-probe.json) copies the direct capability and adds the observed lock/IO families without changing the real specification:

- At version 1.0, the probe reports `COMPAT-04` (added failure modes) and `COMPAT-08` (major version requirement).
- At version 2.0, `COMPAT-04` remains. A major bump is not a compatibility bypass.
- This is a pre-existing descriptive-model discrepancy, distinct from adding new runtime failure behavior. Preserve the original observation, assess consumers and choose a reviewed corrected contract/migration before changing the frozen model.
- The actual YAML and its Python service versions remain unchanged and validate at the existing stage. That metadata result does not close the catalog discrepancy.

## Gate decision and next handoff

- CLI presentation remediation: verified for the named operational cases. Existing rich diagnostics, committed write details, no automatic retry and unexpected-fault propagation are retained.
- Service contract: **rework** under the existing `compilation-failure-review-gap` / MOD-COMP-09. Missing raw helper/IO families need explicit contract correction and consumer disposition.
- Recovery protocol: keep stage/pending ownership, transport status and retry eligibility explicit. Review cached-preview retention against actual server pending state and exact transport fault mappings before claiming complete adapter conformance.
- Keep classification, measured quality categories, formal lock/compensation/crash assessment and whole-product release open. Maintainers own acceptance.
