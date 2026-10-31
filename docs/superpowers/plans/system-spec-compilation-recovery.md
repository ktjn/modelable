# Compilation transport and recovery characterization

- Baseline: Modelable PR #895 merged as `5c7d13530886f6428bcc2af793da2e1c56b88237`; system-spec feedback PR #40 merged as `9e11cd8`.
- Scope: exercise compilation failures through the real stdio JSON-RPC server, observe committed writes and pending/retry recovery, and feed evidence-quality findings back to system-spec.
- Preserve frozen primary contracts and prior historical captures. Source tracing found that successful promotion followed by staging-cleanup failure loses the committed outcome; repair both direct/apply paths using the existing committed-error contract, and refresh affected source bindings/evidence. Archive the completed CLI-error plan/review; keep the ongoing compilation adoption specification active.
- Use existing checkouts and native gates. Source review and a successful transport round trip are insufficient fault-path evidence.

## TODO

- [x] Refresh merges and trace service, JSON-RPC and editor recovery paths.
- [x] Add failing direct/apply and real-transport regressions for successful promotion followed by staging-cleanup failure.
- [x] Preserve committed writes/cleanup detail using the existing committed-error type; retain ordinary failure behavior.
- [x] Add deterministic transport guard/stale/recovery characterization with filesystem postconditions.
- [x] Record source-bound results, actual fault codes, recovery limits and compatibility/artifact checks.
- [x] Feed discoveries into system-spec process guidance and prepare its scoped PR (#41).
- [x] Run required precommit checks and prepare final-commit native-gate/PR delivery.

## Acceptance

- Distinguish transport failures from successful RPCs carrying domain errors and committed-with-cleanup-warning outcomes.
- Verify whether the same pending action is retryable, already cleared, or requires cleanup; inspect writes/staging rather than relying on reply text or editor cache.
- Inject deterministic test-only faults without runtime test hooks; record injection boundaries and avoid claiming OS/crash coverage.
- Keep frozen-catalog correction, untested mappings, quality/classification/formal review and human acceptance explicit.

Initial evidence: both new service regressions failed with ordinary `CompilationError`; the native JSON-RPC regression returned `kind=error` after writes committed. After the cleanup-outcome repair, all eight new tests passed. Guard faults return observed `-32603` and retain staging for corrected retry; stale apply returns a domain error, removes staging and rejects old apply/discard IDs. A committed cleanup warning clears pending ownership but retains the failed staging directory for explicit recovery.

Code-commit gate: Ruff format/check and mypy baseline passed; full Python suite 3,196 passed, 67 skipped, zero reruns. Primary YAML remains metadata-valid at verification; prior source hashes/evidence are historical until the source-bound refresh in the following documentation commit.

Fresh source-bound capture: Windows 238 passed, two skips; Linux four passed, zero skips. Verification/artifacts/inventory and declared-contract compatibility pass; four negative probes reject stale bindings, unexecuted cases, bad source hashes and passing-evidence supersession. Scoped metadata byte preservation passes forced-autocrlf index/checkout/archive checks. Native gate, push and remote CI remain incomplete until recorded in the delivery PR.

Documentation/evidence-commit precheck: Ruff format/check and mypy baseline pass; Python 3,196 passed, 67 skipped, one rerun of the existing marked `test_concurrent_virgin_lock_parent_creation_enters_normal_contention`. Full diff checking retains one trailing-space diagnostic in the raw pytest assertion-separator output (`recovery-rpc-red.txt:9`); captured bytes are preserved. Final native gate/publication/CI remain tracked in the delivery PR.
