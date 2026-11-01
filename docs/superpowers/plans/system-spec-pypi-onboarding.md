# Published system-spec toolkit onboarding

- Scope: use PyPI `system-spec-ref==0.1.0` and its exported WIRING/CONSTITUTION/BROWNFIELD instructions for Modelable's existing adoption.
- Baseline: Modelable #897 merged as `cd1c59aca64aea8c22c1cf10fb0be6ff0696d48f`. Archive the completed proposal-preparation plan; active contract and consumer acceptance work remains open.
- Preserve existing specification paths, source/evidence history and native gates. Keep the toolkit export intact at `tools/system-spec`; pin published wheel/export provenance separately from historic captures.
- Work in the existing Modelable checkout. Preserve concurrent system-spec work and local main.

## TODO

- [x] Verify the installed tool against the published PyPI wheel and read packaged instructions.
- [x] Export the intact toolkit and validate inventory, compilation and proposal at their existing stages.
- [x] Wire agent instructions, bounded-context commands, schema/track references, skill-guide pointers and upgrade procedure.
- [x] Record package/export/dependency provenance and packaged/offline validation parity, retaining historical pins and expected incompatibility/release failures.
- [x] Feed onboarding findings upstream: system-specification PR #50 (WIRING/provenance/history guidance).
- [x] Mandatory precommit checks pass (Ruff format/check, mypy ratchet, 3217 tests passed / 67 skipped, zero reruns). Exact-byte Git checkout/archive and project-doc links verified. Configure the native hook; exact-commit prepush, publication and remote CI results are recorded externally in the delivery PR.

## Acceptance

- Tool available as `system-spec`, verified PyPI distribution 0.1.0; package version is distinct from modeled contract versions.
- Agents use the published toolkit instructions plus the brownfield track and existing project specs; no duplicate idealized baseline or false full-conformance claim.
- Every active spec validates at its current stage. The corrected-contract proposal remains unaccepted/incompatible; release blockers and native/manual gates remain explicit.
- Exported file bytes and relative links stay intact through Git. Tools required by optional formal-model guides remain separate prerequisites.
