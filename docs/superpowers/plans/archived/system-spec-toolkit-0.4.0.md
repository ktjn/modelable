# Published system-spec 0.4.0 adoption

- Baseline: Modelable PR #902 merged at `0aa1949afea74e4ba1daa17c312996b7982caa29`; existing checkout, branch `codex/system-spec-0-4-adoption`.
- Scope: exact published toolkit import, current schema and agent wiring; bind existing compilation tests, environments and single-criterion coverage without changing contracts or relabeling execution.
- Preserve prior specification/schema/manifest, package receipts and original source/evidence pins. Correct Linux provenance to its actual test file; retain the log and hashes as artifacts.
- Use planning, scope and structured handoff diagnostics. Retain honest unmet obligations and explicit shared-path allowances; no tool output establishes acceptance.
- Keep the coherent compilation slice in one file. Split specs, domains, imports, external providers, runtime mediation and fakes need separately reviewed topology/isolation facts; do not add them to exercise syntax.

## TODO

- [x] Verify PyPI 0.4.0 wheel, 65 installed files and 62 exact export files; review new schema and workflow features.
- [x] Run published reference suite: 184 passed, two explicit host symlink skips. All three generated schemas match.
- [x] Preserve historical metadata and add observed test bindings, environment and criterion mappings; update current agent/schema wiring.
- [x] Capture 16 installed/offline command pairs, unchanged compatibility/release blockers and seven planning/scope/return/metadata probes.
- [x] Mandatory precommit gates pass: 3247 Python tests, 67 existing skips, no reruns; format/lint/mypy pass. Link review records 299/300 valid local targets and the preserved published release-guide gap. All 62 published files (76 metadata/toolkit files total) pass exact-byte index, forced-autocrlf checkout and archive checks; prior spec/schema/manifest match the baseline. Scoped commit is prepared.
- [ ] Run exact-commit native prepush gate, publish Modelable PR and upstream feedback, and verify remote CI; actual outcomes are recorded in the delivery PR.
