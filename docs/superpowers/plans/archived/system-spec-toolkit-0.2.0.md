# Upgrade published system-spec toolkit to 0.2.0

- Scope: update the installed PyPI tool and intact Modelable toolkit export; preserve authoritative specs, historical evidence and acceptance gates.
- Baseline: Modelable onboarding PR #898 merged as `06c1765cf4ce74c6f496a9a319acc7b8ed8a5a2c`. Work in this existing checkout on `codex/system-spec-0.2.0`; leave the shared system-spec checkout and local main untouched.

## TODO

- [x] Verify latest PyPI version and inspect fresh exported upgrade instructions.
- [x] Verify wheel/installation/export bytes and review schema/validator changes.
- [x] Replace snapshot, update current package instructions and capture new validation; retain prior captures.
- [x] Review onboarding feedback and record remaining obligations; upstream PR #54 documents drift limitations and repairs the exported PyPI link.
- [x] Mandatory precommit checks pass: formatting/lint, mypy ratchet, 3217 tests passed / 67 skipped / one permitted retry of the pre-existing virgin-lock contention test. Verify staged byte round trips and prepare the scoped commit.
- [x] Configure the versioned native pre-push hook and prepare the PR handoff. Exact-commit native publication and remote CI outcomes are recorded externally in the delivery PR; this preparation record does not assert their completion.

## Acceptance

- Installed CLI and repository snapshot are pinned to PyPI 0.2.0 with reproducible provenance.
- Existing specs validate at inventory, verification and architecture respectively, retaining expected proposal/release rejections.
- Upgrade does not relabel historical captures or approve outstanding contract/adoption/release gates.
