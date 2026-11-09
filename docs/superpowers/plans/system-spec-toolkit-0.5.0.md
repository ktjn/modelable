# Published system-spec 0.5.0 adoption

- Baseline: Modelable `deb6d668f4f0b3d3bafe60c715e1d3e6904f1609` (after #908 promotion journaling at `cdab2da7`).
- Scope: exact published `system-spec-ref==0.5.0` toolkit import, updated `schema.json` and agent wiring; refresh source-bound compilation characterization (`240 passed, 2 skipped` on Windows; `4 passed, 0 skipped` on Linux Docker) and reconcile `whole-product.yaml` worktree artifact hashes; bind truthful 0.5.0 metadata (`Component.description`, `Requirement.priority`) without fabricating isolation harnesses, experience specs, or whole-product acceptance.
- Preserve prior specification/schema/manifest (`*-before-toolkit-0.5.0.*`), 0.4.0 receipts, and historical source/evidence pins.
- Archive `docs/superpowers/plans/system-spec-toolkit-0.4.0.md` to `docs/superpowers/plans/archived/system-spec-toolkit-0.4.0.md`.

## TODO

- [x] Verify PyPI `system-spec-ref==0.5.0` wheel (`d39d5daa98e3af302f78c8bd28e1ab341e0d68852c031a4fb79f3d6ad2e65763`), 81 installed files and 78 exact export files; review 0.5.0 schema and workflow additions (`Component.standalone_harness`/`provided_mocks`, `Experience`/`View`/`StateSet`, `Requirement.statement`/`priority`/`owner`/`superseded_by`, `REQ-08`/`REQ-09`, `System.verification_categories`, `--check-isolation`, `--check-report`, `--emit-evidence`).
- [x] Run published 0.5.0 reference suite: 222 passed, 2 explicit host file-symlink skips. All three generated schemas (`--schema`, `--fragment-schema`, `--return-schema`) match installed/offline outputs.
- [x] Preserve pre-0.5.0 specs/schema/manifest, execute fresh Windows (`240 passed, 2 skipped`) and Linux (`4 passed, 0 skipped`) compilation characterization at `deb6d668`, update `compilation.yaml`, `compilation-contract-proposal.yaml`, `whole-product.yaml`, and `handoff-return-template.yaml`, and update agent/README wiring.
- [x] Capture 20 installed/offline command pairs (`packaged-toolkit-validation-0.5.0.json`), unchanged compatibility/release blockers, and 11 negative/scope/0.5.0-feature probes (`--check-report`, `--emit-evidence`, `--check-isolation`, `REQ-08`, `REQ-09`, `EXP-01`, `verification_categories`).
- [x] Mandatory pre-commit gates pass: 3262 Python tests, 67 existing skips, no reruns; `ruff format`, `ruff check`, and `mypy` baseline pass. Link review records 283/283 resolved local targets in `tools/system-spec/` (0 missing). All 78 published toolkit files match exact export SHA-256 hashes and LF line endings.
