# Characterization evidence

- Current capture: [characterization-current.txt](characterization-current.txt), **221 passed, 2 skipped** on Modelable 1.15.2 at `8de5b55bf07cff4a619c6ae25f2c3368290d310b`.
- Exact command, environment, dependency/test hashes and skip names: [characterization-environment.json](characterization-environment.json).
- Current schema/validator/source/artifact pins: [adoption.json](../adoption.json). Source/version bindings and per-record artifact hashes are in [compilation.yaml](../compilation.yaml).
- [migration-validation.json](migration-validation.json): inventory/verification, contract compatibility, context/impact, negative integrity probes and expected release failures. Metadata output is supporting evidence, not product acceptance.
- The historical Windows run skipped two directory-symlink cases. A separate Linux run now covers both against the original source: **2 passed, 0 skipped**. Its evidence supersedes only the MOD-COMP-10 partial record; Windows output and platform limits remain visible. The other eight records cover distinct named tests.
- Historical files remain unchanged: `characterization.txt`, `symlink-coverage.txt`, `validation.json`, and [baseline.json](../baseline.json). Their original spec/schema paths refer to the initial capture at Git commit `5f48ed00`; the original schema is also retained as [schema-baseline.json](../schema-baseline.json).
- Capture paths are repository-relative in the spec, even though these files live beside it. Provenance names one existing file plus an optional `::selector`; other logs/metadata use `artifacts` maps.
- Tests use fixture workspaces and unique temp state. No production data or credentials were used.
- Criterion coverage, source/build authenticity, transitive dependency mapping, quality categories and human acceptance remain independent review obligations.

## Dependency and suitable-host follow-up

- [compilation-imports.tsv](compilation-imports.tsv) and [compilation-types.json](compilation-types.json): static import closure and nineteen declared dataclass shapes, with source hashes and limits in [compilation-discovery.json](../compilation-discovery.json). Ownership/protocol review: [compilation-map.md](../compilation-map.md).
- [symlink-linux.txt](symlink-linux.txt), [symlink-linux.xml](symlink-linux.xml) and [symlink-linux-environment.json](symlink-linux-environment.json): actual two-case Linux result, zero-skip JUnit, exact command, locked packages, immutable source and image pins.
- [symlink-linux.Dockerfile](symlink-linux.Dockerfile) and [symlink-linux-run.py](symlink-linux-run.py): retained build recipe and runner. Prepare the fresh Git-export context as described in the map; source bytes must match the controlled export before executing tests.
- Git export is explicitly `core.autocrlf=false`, `core.eol=lf`; source and test SHA-256 values are verified against Git blobs. Windows source-binding hashes retain their separate exact-checkout-byte convention. Never infer line endings from the host or archive name.
- [adoption-before-dependency-map.json](adoption-before-dependency-map.json) preserves the previous manifest; [dependency-validation.json](dependency-validation.json) records current compatibility, bindings, supersession and remaining release failures.
