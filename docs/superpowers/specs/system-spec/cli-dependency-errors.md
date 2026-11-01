# CLI dependency operational-error remediation

- Source: `41e4716c66b63a8ffb810b657d65891dba7d307f`, based on merged README PR #900 at `05307933a713553c3e7c2d137f421429452033a4` (Modelable 1.15.2).
- Scope: the native `compile` command's presentation of `json.JSONDecodeError` and `sqlite3.OperationalError`. Existing Python service contracts and other adapters are unchanged.
- Decision: use the existing Click `Error:` format and nonzero exit status for these named operational families. Preserve existing diagnostic/committed-write handling and propagate unspecified programming faults. This implements the first bounded remediation from the [consumer handoff](compilation-contract-review.md#next-implementation-handoff).

## Regression and acceptance evidence

- Before implementation, four desired-message cases failed with empty CLI output: injected JSON/SQLite failures and the real compilation paths for a malformed ledger / injected SQLite connection failure. Both programming-fault cases passed. [Original red output](evidence/cli-dependency-errors-red.txt).
- Add only the two exception types to the existing CLI handler. The service still raises its original types; no broad `Exception`, `ValueError` or SQLite base-class catch is introduced.
- [Six new cases](../../../../cli/tests/test_cli_compilation_dependency_errors.py) cover error presentation, `RuntimeError`/SQLite `ProgrammingError` identity, preserved inputs/no publication/staging cleanup, and successful repair/retry. Malformed JSON is a real ledger file; SQLite operational failure is deterministic connection injection, not real disk exhaustion or corruption.
- The two previous CLI as-is assertions in the [catalog suite](../../../../cli/tests/test_compilation_failure_catalog.py) are intentionally changed to desired presentation assertions alongside this behavior change. Original defect output and source hashes remain historical in the [catalog capture](evidence/contract-review-environment.json); they are not relabeled remediation evidence.
- Source-bound capture: **41 passed, zero skipped, zero reruns**, including original CLI committed-write/cleanup details, service exception identity and real stdio recovery tests. [Stdout](evidence/cli-dependency-errors.txt), [JUnit](evidence/cli-dependency-errors.xml), [command/environment/source hashes](evidence/cli-dependency-errors-environment.json). The import path is verified against this checkout; both Git-blob and host checkout hashes are recorded.

| Consumer / gate | Disposition |
|---|---|
| Native CLI / named dependency failures | Verified for captured tests: readable nonzero error, source and malformed ledger retained, no published registry/artifacts/audit, failed staging removed; corrected request compiles successfully. |
| Existing committed errors / programming faults | Existing written-path/cleanup details and both programming-fault identities retained in executed tests. This is not an exhaustive exception guarantee. |
| Service contracts / historical evidence | Active 1.0 and proposed 2.0 YAML, adoption manifest and schemas are byte-identical to baseline. Three service implementation files and the hash-bound original CLI test module are unchanged. CLI adapter evidence is recorded separately; old captures do not establish this new presentation behavior. |
| Proposal compatibility | Three `COMPAT-04` errors remain. Candidate passing evidence stays empty; this partial CLI disposition does not approve activation or establish external-caller compatibility. |
| Conversation / LSP / native editor | No new policy or fault acceptance. Existing transport regression tests pass, but preview normalization, first-turn session/retry/cache ownership and editor fault coverage remain the next handoff. |
| Release / whole-product adoption | Still open, including residual cleanup ownership, classification, quality, shared IR semantics and formal/crash assessment. Native delivery/CI results belong in the final PR and do not close these gates. |

[Validation capture](evidence/cli-dependency-errors-validation.json) retains current-stage/artifact results, unchanged baseline hashes, proposal incompatibility and failing release diagnostics. Historical passing records are preserved; no waiver or assertion is weakened.

## Feedback and next handoff

- Record consumer remediation at its actual boundary: readable CLI errors do not change the service's escaping failure catalog or prove conversation/editor recovery. Keep passing defect characterization separate from desired-behavior acceptance and bind new evidence to its actual adapter source revision.
- No metamodel/schema extension is needed for this disposition. Feed the result into the upstream Modelable onboarding feedback trail with the delivery PR.
- Next: choose preview/LSP/editor operational-failure and session-recovery policy, then add desired fault/retry/close coverage. Maintainers retain activation ownership; unknown external Python consumers remain open.
