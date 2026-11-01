# CLI compilation dependency-error presentation

- Baseline: merged README PR #900 at `05307933a713553c3e7c2d137f421429452033a4`; existing checkout on `codex/cli-compilation-operational-errors`.
- Scope: normalize JSON decoding and SQLite operational failures at the native compile CLI boundary with existing Click errors. Preserve service exception types, diagnostic/committed-path rendering and unspecified programming faults.
- Preserve active 1.0 and unaccepted 2.0 proposal, historical captures and hash-bound tests. Record new CLI evidence independently; conversation/LSP/editor/external-caller acceptance remains open.

## TODO

- [x] New regressions fail as expected before implementation: four missing-message failures; both programming-fault cases pass. Red output retained for evidence.
- [x] Catch only JSONDecodeError and SQLite OperationalError at CLI; update the two as-is CLI assertions intentionally and add a changelog entry.
- [x] Focused 41 tests pass; mandatory formatting/lint/mypy and 3223 tests pass with 67 skips, zero reruns. Commit immutable implementation/test source for the source-bound capture.
- [x] Immutable source-bound capture: 41 passed, zero skips/reruns; consumer disposition and limits updated. Upstream feedback is prepared for publication with the delivery PR.
- [x] Active-stage/artifact, compatibility/release diagnostics, documentation and exact-byte evidence checks pass. Mandatory precommit checks pass again: 3223 passed, 67 skipped, zero reruns. Commit evidence and configure the native-gated publication handoff; final exact-commit push/PR/CI outcomes are recorded externally in the delivery PR.

## Acceptance

- Clear nonzero Click errors for named JSON/SQLite operational failures; source/ledger preserved and no publication after failure; repair/retry succeeds.
- RuntimeError and SQLite ProgrammingError still propagate; existing diagnostic and committed-with-cleanup details remain intact.
- Source/test hashes, actual commands, outputs and gate scope are retained. No contract activation or whole-product acceptance is claimed.
