# Conversation preview operational-failure recovery

- Implementation: `2146fed9327b58518b9f1e67f3b7cc5b1aace7b8`, based on merged CLI remediation #901 at `661e8a41496ca2effad37d13aa45bbb462e46453` (Modelable 1.15.2).
- Scope: named JSON/SQLite preview failures, authoritative pending metadata and native editor retry/cache ownership. Core service exception types and active/candidate contracts are unchanged.
- Decision: catch only JSONDecodeError and SQLite OperationalError alongside existing CompilationError. Unexpected programming faults propagate. Failed replacement retains its live old action; LSP serialization reports that ID/kind only when the backend still owns it. IDs do not bypass freshness/dirty guards or authorize automatic apply.

## Discoveries and repairs

| Boundary | Finding and disposition |
|---|---|
| Error/session ownership | Escaping operational errors entered exception cleanup. Even an already-handled replacement rejection omitted the retained action ID from the wire. Return normal errors and serialize actual pending state; preserve existing backend error-reply fields and avoid client-side ownership guesses. |
| Actual initialize | pygls ignores the user initialize handler return and computes its own capabilities. The direct-helper test passed while the actual response omitted conversation protocol 2. A protocol subclass now merges the existing intended experimental advertisement into the real response, preserving computed negotiation. The new real-initialize regression first failed with experimental=None. |
| Optional model locations | Valid Go previews include go.mod as an affected artifact ID. Parsing every ID as a model reference crashed serialization after staging. Validate optional model-reference conversion separately, retain artifact IDs without invented source locations, and propagate unexpected faults from valid-reference lookup. |
| Test preconditions | Unchanged previews may have no text diff to cache. The reset case creates a new Go preview and establishes cache presence before cleanup assertions. Model-location assertions use the existing resolver's multiline declaration format. Native request spying preserves argument count; cleanup waits for the owned server process to close. |

## Source-bound evidence

- Before the respective fixes: 13 preview/pending failures with four passes; one actual-initialize failure; four artifact-navigation failures with two passing unexpected-lookup-fault checks. [Preview red](evidence/preview-recovery-red.txt), [initialize red](evidence/preview-recovery-initialize-red.txt), [reference red](evidence/preview-recovery-reference-red.txt).
- [Native red](evidence/preview-recovery-native-red.txt): 35 existing passes and two new capability-gate failures before preview requests. That run does not establish later recovery behavior. Red captures are incremental working regressions; the passing runs below bind to immutable final source.
- Python/RPC: **168 passed, one skipped, zero reruns**; all **24 new cases execute**. The skip is an existing documentation-index symlink case requiring unavailable Windows privilege. [Stdout](evidence/preview-recovery-python.txt), [JUnit](evidence/preview-recovery-python.xml).
- Native editor: **37 passed**, including two new real-RPC recovery flows. Real VS Code, LanguageClient, Python server and production conversation/client/cache code are used; chat registration/history/stream are driven programmatically. [Native output](evidence/preview-recovery-native.txt).
- [Environment/source hashes](evidence/preview-recovery-environment.json) retain commands, dependency versions, imported checkout path, Git-blob/checkout hashes and native compiled-test/log hashes. SQLite faults are deterministic connection injection, not actual storage corruption/exhaustion.

| Scenario | Executed result |
|---|---|
| First-turn JSON/SQLite failure | Normal error includes session metadata with no pending ID; source/ledger are preserved, no publication or failed stage remains, and repaired retry continues the same session and applies. |
| Failed replacement | CompilationError/JSON/SQLite retain old stage bytes and identity. The wire reports the live compile or source-change action. Repaired old compilation applies, or close removes its stage. |
| Native history/cache | Random first-turn ID is recovered from chat metadata; retry uses createSession=false. Replacement retains cached snapshots; explicit apply checks published-byte hashes and clears cache. Reset closes a new cached preview and removes cache/staging; closed sessions reject continuation. |
| Unexpected faults | RuntimeError/SQLite ProgrammingError retain identity and protocol-fault behavior. Valid-reference lookup RuntimeError/ValueError is not swallowed. Non-model parsing is optional navigation validation only. |
| Contracts | Active 1.0 and unaccepted 2.0 YAML, schema, adoption manifest and core source bindings remain byte-identical. Earlier CLI/defect evidence stays historical. |

## Decision and remaining gates

Named operational preview recovery and the captured automated RPC/editor paths are verified within this scope. [Validation](evidence/preview-recovery-validation.json) retains current-stage/artifact checks, three COMPAT-04 proposal errors and failing release checks. Exact-commit delivery/native-gate/CI outcomes belong in the PR.

- Feed actual handshake, pending ownership and reference-kind assumptions upstream. No protocol fields, metamodel/schema extension or contract activation are added.
- Normal close/apply/reset cleanup is covered. Faulting close, residual cleanup/crash ownership, stale-apply cache policy, other operational families and unknown external consumers remain open.
- Real-model/manual chat, universal source-format/platform acceptance, quality, classification, shared IR semantics, formal assessment and whole-product release remain open. Maintainers retain acceptance ownership.

Raw-evidence formatting: the captured native-red stack trace has two space-before-tab indents (lines 219 and 229). Full diff hygiene reports them; exact captured bytes/hashes are retained. Project-authored files pass the separate whitespace check. No Git whitespace policy, test assertion or coverage gate is relaxed.
