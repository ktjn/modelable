# System-spec evidence migration

- Scope: repair the native-gate graph overlap discovered during delivery, and migrate the bounded compilation slice to explicit contract/source bindings and local artifact integrity; preserve the historical intake and evidence.
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

## Approved native-gate repair

- User approved repairing the product graph layout and continuing publication.
- Discovery: the original dense-graph assertion failed once in eight runs; waiting for the requested layout made the unchanged overlap assertion fail in all eight runs. Geometry still overlapped after a 250 ms diagnostic wait.
- Repair boundary: move zoom/fit/navigation controls above the graph canvas; preserve React Flow behavior, zoom bounds and all overlap assertions. Wait for the requested layout in the existing browser test.

- [x] Reproduce the product discrepancy with the stronger readiness check before implementation.
- [x] Repair navigation placement and add the required changelog entry.
- [x] Verify dense modes under eight-worker load, responsive layout and control functionality.
- [x] Run required precommit checks for the repair and record results.
- [x] Record repair feedback and prepare exact-commit native-gate publication.

Remote publication/check state remains recorded in the PR, independently of this local implementation plan.

Repair validation: TypeScript/build and fifteen targeted graph unit tests passed; eight dense-mode repetitions passed with eight workers, including zoom/fit interactions; nine related graph/responsive scenarios passed. Captured browser-frame review confirms controls sit above the canvas.

Repair precommit gate: Ruff format/check and mypy baseline passed; full Python suite 3,182 passed, 67 skipped. Repair feedback is pushed in system-specification PR #38. Exact-commit native push/remote CI outcomes remain delivery evidence in the Modelable PR.
