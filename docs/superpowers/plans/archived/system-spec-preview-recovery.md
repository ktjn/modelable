# Conversation compilation preview recovery

- Baseline: CLI remediation PR #901 merged at `661e8a41496ca2effad37d13aa45bbb462e46453`. Existing checkout, branch `codex/conversation-preview-recovery`.
- Scope: known JSON/SQLite preview failures become normal conversation errors; programming faults propagate. Preserve valid pending actions, and serialize authoritative pending IDs for LSP error replies so editor history/cache ownership survives failed replacement.
- Discovery: server-side pending preservation alone is insufficient when the latest wire error omits its ID. Existing backend reply behavior can stay unchanged; LSP serialization should attach IDs only from a still-live pending action.
- Required supporting discovery: pygls ignores the user initialize handler return and recomputes wire capabilities. Add a real initialize regression and advertise the existing conversation capability through the supported protocol subclass hook. Native red failures initially occur at this capability gate, before preview requests.
- Required serialization discovery: valid Go previews include `go.mod` as an affected artifact reference. Optional model-location lookup must return no location for non-model references while preserving faults from valid-reference lookup; keep artifact IDs in the reply.
- Keep active service contracts and the candidate 2.0 proposal unaccepted. Native editor tests exercise real language-client transport with deterministic compile commands, not real-model/manual chat acceptance.

## TODO

- [x] Regression-first evidence: Python 13 expected failures / 4 passes; native editor 2 capability-gate failures / 35 existing passes. Both red outputs retained.
- [x] Catch only named JSON/SQLite operational failures alongside existing CompilationError; attach live pending metadata at LSP serialization and intentionally update the old RPC defect assertion. Real initialize and artifact-reference failures have separate red regressions and narrow supporting fixes.
- [x] Mandatory format/lint/mypy and full Python checks pass: 3247 passed, 67 skipped, zero reruns. Native editor suite passes all 37 tests. Commit immutable source; capture its new evidence separately from historical runs.
- [x] Source-bound capture: 168 Python/RPC passes / one existing symlink skip; 37 native passes. Consumer decisions, validation and remaining gates are recorded; upstream feedback is prepared for publication.
- [x] Evidence hashes, 66 local documentation links and Git byte round trips verified; mandatory precommit checks pass again (3247 passed / 67 skipped / zero reruns). Native hook and PR handoff are prepared; exact-commit publication/CI and upstream feedback outcomes are recorded in the delivery PR. Two raw stack-trace whitespace diagnostics are retained and documented.

## Acceptance

- First-turn operational failure returns a normal error with session metadata, leaves no publication/staging, and permits repaired retry.
- Failed replacement retains the actual old pending stage and wire ID; apply/discard or close has explicit, tested ownership. No old action is invented after removal.
- Real native VS Code client/participant tests recover history, preserve cache on replacement failure, and clean cache/staging on apply/reset.
- RuntimeError and SQLite ProgrammingError remain faults; no broad catch, protocol field additions, assertion weakening or contract activation.
