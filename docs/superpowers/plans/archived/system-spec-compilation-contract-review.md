# Compilation failure-contract correction proposal

- Baseline: Modelable #896 merged as `940a76b21f503621cda895642f1a2fb6b465a293`; system-spec #42 merged as `31776f5`.
- Scope: characterize escaping operational errors per operation, trace internal consumers and prepare a proposed corrected catalog with explicit compatibility/consumer disposition.
- Preserve active `compilation.yaml` version 1.0 and current evidence. Proposed descriptions are review artifacts, not new published Python APIs or accepted migration.
- Archive the merged recovery implementation plan. Keep its source-bound adoption/recovery records active because their contract/recovery acceptance obligations and manifest references remain open.
- Existing checkouts only. Leave local system-spec `main` and the unrelated `uv.lock` untouched.

## TODO

- [x] Refresh merges and trace service/helper/CLI/conversation/LSP boundaries.
- [x] Add as-is fault characterization with identity, filesystem and cleanup assertions.
- [x] Prepare per-operation proposed failure sets, internal/unknown consumer dispositions and expected compatibility diagnostics.
- [x] Capture exact runtime/test/source/artifact bindings; validate active/proposed metadata and negative probes.
- [x] Implement the resulting process guidance in system-spec and publish its scoped PR (#44).
- [x] Run mandatory precommit checks and prepare final-commit native delivery; publication/CI results belong in the PR.

## Acceptance

- Distinguish wrapping, escaping exceptions, guarded/unreachable paths and unspecified programming faults; do not union every dependency error into every operation.
- Preserve nonzero compatibility diagnostics for added failure modes, even with a major modeled version.
- Separate source/model correction from a runtime change and from consumer approval. Unknown external callers and uncovered fault paths keep activation in rework.
- Schema validation and existing characterization do not establish closed/exhaustive exception coverage, crash guarantees or whole-product acceptance.

Characterization: 35 passed, zero skipped/reruns, including 21 new as-is cases. Active specification/adoption/schema are byte-identical to merged main and artifact-valid. The proposed versions retain three COMPAT-04 diagnostics; old evidence copied to candidate versions is rejected with EV-04 and bad runtime hashes are rejected. Pinned validator bytes are extracted from the known toolkit revision; the concurrently active toolkit checkout is not used as the validator authority.

Precommit gate: Ruff format/check and mypy baseline passed; full Python suite 3,217 passed, 67 skipped, zero reruns. System-spec #44 merged with successful CI (125 tests and example validations). Final native gate, push and remote build remain external delivery obligations recorded in the PR.
