# System-spec evidence migration

- Scope: migrate the bounded compilation slice to explicit contract/source bindings and local artifact integrity; preserve the historical intake and evidence.
- Branch: `codex/system-spec-evidence-migration`; work in the existing checkout.
- Product baseline: `8de5b55b` (1.15.2). Whole-product inventory remains the historical 1.15.1 observation.

## TODO

- [x] Inspect merged changes, existing authorities, baseline and native gates.
- [x] Reproduce old provenance/binding incompatibility with the current validator.
- [x] Rerun focused characterization; bind source, tests, results and current schema.
- [x] Record compatibility, negative integrity checks, skips and open acceptance obligations.
- [x] Feed migration findings back to system-specification.
- [x] Run required precommit checks and prepare bounded delivery artifacts.

## Acceptance

- Inventory and compilation verification pass with explicit repository-root artifact checks.
- Capability/data compatibility with the original capture passes; all eight current evidence bindings satisfy EV-04.
- A changed source/log or stale binding is rejected; omitted/skipped checks never become passes.
- Native gates remain mandatory. No whole-product/release acceptance or formal proof is inferred.

## Delivery record

- Precommit validation: Ruff format/check and mypy baseline passed; Python 3,182 passed, 67 skipped.
- Publication and exact-commit native-gate results are recorded in the PR description/checks. This implementation plan records the completed local artifact migration; it does not assert release acceptance.
