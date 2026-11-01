# Compilation failure-catalog correction review

- Original catalog-review baseline: [compilation.yaml](compilation.yaml), modeled contracts 1.0. Runtime reviewed at merged `940a76b21f503621cda895642f1a2fb6b465a293` (package 1.15.2); implementation files match the active pinned runtime. That original review changed no runtime/API implementation, dependencies or active evidence. The subsequent [CLI dependency-error remediation](cli-dependency-errors.md) changes presentation only; service contracts/bindings remain unchanged.
- Proposed description: [compilation-contract-proposal.yaml](compilation-contract-proposal.yaml), direct/preview/apply 2.0; discard 1.0. This is a correction proposal for observed behavior, not a published Python package version or approved migration.
- Result: **rework before activation**. [Compatibility diagnostics](evidence/contract-compatibility.json), [capture](evidence/contract-review-environment.json), [stdout](evidence/contract-characterization.txt), [JUnit](evidence/contract-characterization.xml), [validation](evidence/contract-review-validation.json). Process feedback: [system-spec #44](https://github.com/ktjn/system-specification/pull/44).

## Per-operation correction

The table names bounded, observed operational families missing from the frozen description. It is not an exhaustive Python exception guarantee. Existing declared errors, postconditions, invariants, interfaces and all five data models are preserved in the proposal.

| Operation | Proposed additions | Executable boundary / state | Exclusions and limits |
|---|---|---|---|
| Direct | `RegistryIdLockContentionError`, `LockContentionError`, `OSError`, `json.JSONDecodeError`, `sqlite3.OperationalError` | Injected ledger entry/publication contention, staging allocation IO and SQLite connection failure; a real malformed input ledger. Exact exception identity retained, input preserved, no published output/audit and staging removed. | OCI helper failures are already wrapped as `CompilationError`; no new OCI error mode. Programming/dependency faults remain possible. |
| Preview | `OSError`, `json.JSONDecodeError`, `sqlite3.OperationalError` | Staging allocation, malformed input ledger and injected SQLite connection failure; no publication and no surviving failed stage. Preview also succeeds while the destination ledger lock is held. | It does not acquire the direct/apply publication locks. Their contention classes are not copied into this operation. |
| Apply | `RegistryIdLockContentionError`, `LockContentionError`, `OSError` | Valid preview followed by ledger/publication contention or staged audit IO; exact exception identity retained, stage removed and no outputs/audit published. | Apply promotes staged bytes rather than rebuilding the SQLite registry. No raw database/decoder addition is inferred merely from imports. Existing staleness and committed-error behavior remains separately declared. |
| Discard | None; keep version 1.0 | Injected removal IO is wrapped in `CompilationError`, preserves the original cause and leaves staging for cleanup. | Do not add raw `OSError` when this boundary normalizes it. Unexpected failures are not exhaustively enumerated. |

The [21 new as-is cases](../../../../cli/tests/test_compilation_failure_catalog.py) also preserve `RuntimeError` and SQLite programming-fault identity in direct/preview. They characterize the current boundary; they do not normalize all SQLite failures or prove every emitter, extension, path-race or dependency fault. SQLite failures are deterministic connection injection, not real disk exhaustion or corruption. Lock injection does not prove scheduler/concurrency properties.

## Consumer disposition

| Consumer / ownership | Observed behavior / evidence | Required disposition and acceptance |
|---|---|---|
| Native CLI / Modelable maintainers | Original defect capture exposed raw JSON/SQLite operational exceptions without normal Click presentation. [Source-bound remediation](cli-dependency-errors.md) now renders the named failures, preserves committed details/programming faults, and verifies corrected retry. | **Named CLI remediation verified:** 41 focused tests pass. Original as-is capture remains historical; this does not approve other consumers, exhaust the failure catalog or activate the proposal. |
| Filesystem conversation / Modelable maintainers | Preview catches `CompilationError`; JSON/SQLite failures can escape through session cleanup. Apply catches ordinary exceptions into domain replies and distinguishes committed cleanup. Source plus existing/native characterization covers named paths. | **Review/rework:** choose error normalization and recovery for preview failures; retain commit/cleanup/pending ownership distinctions. SQL fault transport is not executed by this capture. |
| Native LSP / Modelable maintainers | A real malformed-ledger preview returns JSON-RPC `-32603`. Repairing the ledger permits preview/apply using the same explicit server session, with exact published-byte checks. | This is the observed current transport, not a proposed error-code API. Decide whether operational failures should be domain replies or protocol faults; add required fault/recovery checks before approval. |
| VS Code client/participant / Modelable maintainers | Source review: request metadata is recovered from prior successful chat results. A failed first turn may create a server session before reply metadata exists; noncancelled errors are rendered through the sanitized error path. | **Unverified:** an explicit-session LSP retry does not prove editor history/session recovery. Verify creation-failure/retry/close behavior and preview cache ownership before acceptance. No native editor fault-injection result is claimed. |
| External Python callers / ownership unknown | No external caller inventory or handling/acceptance evidence is available. Repository scan found public service calls in the CLI and filesystem conversation; the session facade forwards service ownership. | **Open:** discover consumers, communicate the corrected description and obtain a migration/recovery disposition. Unknown is not implicitly compatible. |

The caller scan covers `cli/src`, `cli/scripts`, `web/src` and VS Code source, excluding generated/dependency/test trees. Browser protocol and other integrations have their own authorities; this service-catalog review does not establish their conformance.

## Compatibility and evidence decision

- The active 1.0 specification, source bindings, passing records and [adoption manifest](adoption.json) remain byte-for-byte unchanged.
- Proposed metadata validates at **architecture** using the pinned metamodel/schema. Candidate requirements are specified, all candidate passing evidence is empty, and MOD-COMP-11 requires consumer review before activation. Metadata validity does not approve the change.
- Three `COMPAT-04` diagnostics remain for the changed failure sets at major version 2.0. A same-version probe additionally produces three `COMPAT-08` diagnostics. A major version is not a compatibility bypass.
- The proposal retains source/version bindings as proposed descriptions, without copying old passing records onto the new versions. Before activation, review changed obligations and align evidence explicitly; preserve this baseline and diagnostics.
- Runtime files are bound to immutable merged `940a76b2`; new test definitions are separate hashed PR artifacts, not claimed to exist at that baseline commit. Final delivery commit/native validation is recorded in the PR.
- Broader capture: **35 passed, zero skipped, zero reruns**, including the 21 new cases and existing CLI/cleanup/real-RPC recovery tests. The full native gate remains a separate delivery obligation.

## Next implementation handoff

- Acceptance owner: Modelable maintainers; external consumer ownership remains unknown. Prepared by source review and retained local execution, without assuming maintainer approval.
- Earliest affected gate: observed failure-contract correction / consumer compatibility. Keep active 1.0 until a reviewed correction, consumer handling and evidence plan are accepted.
- First bounded remediation complete for the named CLI families: [handling decision and source-bound evidence](cli-dependency-errors.md). Six new desired-behavior cases pass; the two CLI as-is assertions are intentionally updated with the behavior change. Service catalog tests and programming-fault checks remain intact.
- Follow with preview/LSP/editor recovery policy and missing fault coverage. Keep residual cleanup ownership, classification, shared IR semantics, measured quality categories, formal lock/compensation/crash assessment and whole-product release open.
