# Characterization evidence

- Current capture: [characterization-current.txt](characterization-current.txt), **221 passed, 2 skipped** on Modelable 1.15.2 at `8de5b55bf07cff4a619c6ae25f2c3368290d310b`.
- Exact command, environment, dependency/test hashes and skip names: [characterization-environment.json](characterization-environment.json).
- Current schema/validator/source/artifact pins: [adoption.json](../adoption.json). Source/version bindings and per-record artifact hashes are in [compilation.yaml](../compilation.yaml).
- [migration-validation.json](migration-validation.json): inventory/verification, contract compatibility, context/impact, negative integrity probes and expected release failures. Metadata output is supporting evidence, not product acceptance.
- The two directory-symlink cases did not execute. Their explicit skipped record belongs to MOD-COMP-10; it has no passing evidence. The other eight evidence records cover distinct named tests.
- Historical files remain unchanged: `characterization.txt`, `symlink-coverage.txt`, `validation.json`, and [baseline.json](../baseline.json). Their original spec/schema paths refer to the initial capture at Git commit `5f48ed00`; the original schema is also retained as [schema-baseline.json](../schema-baseline.json).
- Capture paths are repository-relative in the spec, even though these files live beside it. Provenance names one existing file plus an optional `::selector`; other logs/metadata use `artifacts` maps.
- Tests use fixture workspaces and unique temp state. No production data or credentials were used.
- Criterion coverage, source/build authenticity, transitive dependency mapping, quality categories and human acceptance remain independent review obligations.
