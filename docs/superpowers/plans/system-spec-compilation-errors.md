# Compilation error boundary review

- Scope: characterize actual compilation exceptions and CLI/conversation/LSP/VS Code translation; repair known CLI operational-error presentation while preserving Python exception types, existing diagnostics and committed outcomes.
- Review input: Modelable PR #894 merged as `5b32a5af`; its completed dependency-map plan is archived in this follow-up. The CLI fix is delivered independently from refreshed main.
- Source baseline: merged main `5b32a5af2d2b8e7c47a4c878fba554ceed801bba` (same reviewed tree as `f03c7353`); preserve the original frozen capability/data contracts and historical captures.
- Work in the existing checkouts; publish system-spec feedback separately.

## TODO

- [x] Refresh PR/main state and trace service plus adapter error paths.
- [x] Add CLI regression tests and confirm the expected failures before implementation.
- [x] Translate known operational failures into CLI errors, retaining committed write details and unexpected-fault propagation.
- [ ] Review the actual error/cleanup matrix and record contract discrepancies without silently redefining version 1.0.
- [ ] Run targeted characterization, compatibility/artifact checks and feed findings back to system-spec.
- [ ] Run required precommit checks and prepare exact-commit native-gate delivery.

## Acceptance

- Known transaction, lock and filesystem errors produce an actionable CLI failure; committed cleanup errors retain their outcome, written paths and cleanup details.
- Existing rich parse/semantic diagnostics and Python service exception identity remain unchanged; unexpected programming faults are not swallowed.
- CLI, shared filesystem conversation and LSP/VS Code translation are distinguished. Schema validation is not proof that the failure catalog is complete.
- Native gates and remaining conformance obligations stay in force. Publication/remote CI are recorded in the PR independently of local plan completion.

Initial CLI regression: five failed, one passed for the expected missing-message behavior. After the CLI-only fix, sixty-nine related CLI tests passed; the wider service/conversation/LSP characterization passed 295 tests with six explicit platform skips. The source-bound capture will be rerun against the code commit before publishing the review artifacts.

Code-commit gate: Ruff format/check and mypy baseline passed; Python 3,188 passed, 67 skipped, 1 rerun. The repository has an existing marked FileTransaction thread-timing retry policy; no retry configuration or assertions were changed. The short report did not retain the failing-attempt details, so the rerun qualification remains explicit.
