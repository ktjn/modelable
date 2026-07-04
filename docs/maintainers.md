# Maintainer and Agent Guide

This document defines how automated and human-assisted agents operate within the
[Project Governance](https://github.com/ktjn/modelable/blob/main/GOVERNANCE.md).
It is process guidance for agents, not product semantics. The product source of
truth remains
[architecture.md](architecture.md).

## 1. Purpose

Agent governance exists to keep repository changes reviewable, locally
verifiable, and aligned with Modelable's core contract guarantees and
[Product Principles](https://github.com/ktjn/modelable/blob/main/GOVERNANCE.md#3-product-principles-in-governance):

- Published model and projection versions are immutable.
- Incompatible changes require new versions.
- Lineage, compatibility, governance findings, and generated artifacts must be deterministic.
- Adapter-specific details must not leak into platform-neutral model and projection definitions.
- PII, restricted fields, and unauthorized fields must not be exposed through projections, generated artifacts, logs, or dead-letter payloads.

These rules apply to documentation, samples, future source code, tests, generated artifacts, CI configuration, and PR preparation.

## 2. Agent Operating Rules

Agents must:

- Consult [AGENTS.md](https://github.com/ktjn/modelable/blob/main/AGENTS.md)
  for the current project state and
  [ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) for
  planned work before starting.
- Read the relevant specification before editing.
- Keep changes small enough for meaningful review.
- Add or update tests with any code change that affects parser behavior, validation, compatibility checks, lineage, planning, runtime execution, governance, security, or generated artifacts.
- Prefer behavior and contract tests over implementation-shape tests. A test
  should normally exercise the public command, exported function, generated
  artifact, policy contract, or workflow behavior. Avoid assertions that only
  prove a private helper, literal string, control-flow shape, or file layout is
  present unless that detail is itself the reviewed contract.
- Add Docker-backed compile smoke tests for any change that adds or modifies a generated-language backend or generated artifact format, using the latest official compiler/runtime image for each affected language.
- Run the OpenMetadata Testcontainers smoke for any change that can affect the
  OpenMetadata export format, including `openmetadata` emitter code, shared
  emitter metadata helpers, IR field/governance metadata shape, projection
  lineage resolution, or OpenMetadata CLI/documentation contracts.
- Run the Marquez/OpenLineage Testcontainers smoke for any change that can
  affect OpenLineage event export or live lineage synchronization, including
  `openlineage` emitter code, the OpenLineage registry client, sync command
  wiring, shared emitter metadata helpers, projection lineage resolution, or
  OpenLineage CLI/documentation contracts.
- Run the Data Contract CLI lint smoke for any change that can affect the ODCS
  export format, including `odcs` emitter code, shared emitter metadata helpers,
  IR field/governance metadata shape, or ODCS CLI/documentation contracts.
- Run the HL7 FHIR Validator smoke for any change that can affect the FHIR R4
  profile export format, including `fhir-profile` emitter code, shared emitter
  metadata helpers, IR field/governance metadata shape, or FHIR CLI/documentation
  contracts.
- Do not use hard-coded line numbers to locate language elements in test fixtures or sample files. Derive line positions dynamically.
- Validate current latest stable framework, library, CLI, build-tool, and scaffolding choices with a web search against official documentation, package registries, or release pages before adding or changing them.
- Use the latest stable framework and tool versions by default, unless the specification, compatibility constraints, existing manifests, or explicit user direction require a different version.
- Record any deliberate use of an older framework or tool version in the final handoff or PR body.
- Use `uv` exclusively for Python version management, project setup, dependency management, lockfile generation, and tool execution. Keep packages up to date with the latest stable versions.
- The project requires Python >= 3.14 (declared in `cli/pyproject.toml` `requires-python` and `[tool.mypy] python_version`). All agents and CI must run under Python 3.14+ for Pydantic v2 validation and modern typing behavior. Strict mypy is enforced as a CI baseline ratchet: existing errors are tracked in `cli/mypy-baseline.txt`, new errors fail the Validate workflow, and resolved baseline lines should be removed as modules are cleaned up.
- Preserve the existing domain language: domain-owned canonical models, immutable versions, projections, subscriptions, adapter bindings, planner/runtime/materializer, compatibility, lineage, and governance.
- Maintain backward compatibility within major versions for the `.mdl` language and CLI.
- Prefer explicit derivation and traceability over implicit behavior.
- Identify whether a change is MVP, deferred, non-goal, or open decision when adding requirements.
- Avoid broad architecture or tooling churn unless it directly supports the requested change.
- Record verification evidence in the final handoff or PR body.
- **Local CI Requirement**: Run the full local gate and ensure all tests pass before reporting a task as complete or creating a PR.
- **GitHub Verification**: Verify that GitHub Actions CI passes for any pushed changes.
- **Strategic Re-evaluation**: If a fix fails more than 3 times, stop and re-evaluate assumptions. Propose an alternative architectural approach rather than continuing to patch a failing one.

Agents must not:

- Weaken published-contract semantics.
- Reclassify governance findings as non-blocking implementation details without documenting the policy decision.
- Collapse registry, compiler/planner, runtime, materializer, and adapter boundaries for convenience.
- Commit transient local artifacts such as dependency folders, build outputs, caches, test result directories, local environment files, or fetched Helm dependencies.

## 3. Local Gate

Every completed change must pass a local gate before it is reported as complete.

Minimum local gate:

```text
git status --short
review changed-file diff
run relevant tests or checks
report commands run and skipped checks
```

Documentation-only local gate:

```text
git status --short
review Markdown diff
confirm links and document references are coherent
confirm terminology matches the system specification
```

CLI implementation local gate:

```text
git status --short
uv sync --extra dev
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ -v
uv run modelable validate tests/fixtures/customer.mdl
```

Run these commands from `cli/`. The final non-mutating Ruff checks are required
after any auto-fix or formatting step; they mirror the first CLI gates in
GitHub Actions and prevent unformatted changes from skipping the test suite.
If the formatter or static-analysis commands change, update this section,
[AGENTS.md](https://github.com/ktjn/modelable/blob/main/AGENTS.md), and
[CONTRIBUTING.md](https://github.com/ktjn/modelable/blob/main/CONTRIBUTING.md)
together.
**If a milestone is completed, update the status table in
[AGENTS.md](https://github.com/ktjn/modelable/blob/main/AGENTS.md).**

For LSP or VS Code extension changes, also run:

```text
cd vscode
npm ci
npm run build
npm test
```

On Windows, close any running desktop VS Code windows before `npm test`; the smoke runner fails fast if the desktop app is still holding the update mutex.

For release pipeline or packaging metadata changes, also run:

```text
cd cli
uv run pytest tests/test_release_metadata.py tests/test_release_workflow.py -v
```

## 4. Test Gates

Test gates are selected by risk and touched surface.

| Touched surface | Required gate |
|---|---|
| Documentation only | Markdown diff review, link/reference coherence check, terminology check against the system spec |
| `.mdl` samples or fixtures | `uv run modelable validate <path>` from `cli/` when the touched file is expected to be supported by the current parser/compiler; otherwise manual grammar and semantic review with the unsupported construct stated in the handoff |
| Parser, IR, or semantic validation | Focused parser/validation tests plus the full local compiler gate |
| Planner, lineage, compatibility, or governance | Focused tests for changed behavior plus representative projection and governance fixtures |
| Emitters or generated artifacts | Focused emitter tests, deterministic output comparison, fixture regeneration review, and Docker-backed compile smoke tests for every affected language backend |
| OpenMetadata export format | `uv run pytest tests/test_emit_openmetadata.py -q` plus `MODELABLE_OPENMETADATA_TESTCONTAINERS=1 uv run pytest tests/test_openmetadata_testcontainers.py -q` from `cli/` |
| OpenLineage export or sync format | `uv run pytest tests/test_emit_openlineage.py tests/test_openlineage_sync.py -q` plus `MODELABLE_OPENLINEAGE_TESTCONTAINERS=1 uv run pytest tests/test_openlineage_testcontainers.py -q` from `cli/` |
| ODCS export format | `uv run pytest tests/test_emit_odcs.py -q` plus `MODELABLE_DATACONTRACT_CLI=1 uv run --with datacontract-cli pytest tests/test_emit_odcs.py --tb=short -q` from `cli/` |
| FHIR R4 profile export format | `uv run pytest tests/test_emit_fhir.py tests/test_fhir_validator.py -q` plus `MODELABLE_FHIR_VALIDATOR=1 MODELABLE_FHIR_VALIDATOR_JAR=<path-to-validator_cli.jar> uv run pytest tests/test_fhir_validator.py --tb=short -q` from `cli/` when the HL7 validator jar is available |
| LSP, VS Code extension, or editor integration | Focused LSP tests plus `cd vscode && npm ci && npm run build && npm test` |
| Release pipeline or packaging metadata | Focused release metadata/workflow tests plus the full local CLI gate |
| Runtime, subscriptions, adapters, or materializers | Unit tests, integration or smoke tests for the adapter boundary, and failure-mode coverage |
| Security, permissions, PII, or restricted fields | Negative tests proving unauthorized exposure is rejected or reported as a governance finding |

Compatibility, lineage, and governance tests must include negative cases when behavior can fail unsafely.

Workflow and policy tests should exercise reusable scripts or parse structured
workflow data where feasible. Avoid broad "contains this exact text" assertions
for CI behavior when the same requirement can be checked by running the routing
logic, parsing the workflow jobs, or inspecting generated outputs.

## 5. Pull Request Handling

PRs should be narrow and explicit.

Every PR should include:

- Intent: what product or repository behavior changes.
- Scope: documents, modules, samples, or generated artifacts touched.
- Verification: exact local commands or checks run.
- Risk: compatibility, lineage, governance, PII, generated artifact, or runtime risks.
- Deferred work: any intentionally skipped follow-up.

PRs that change published contract semantics, compatibility rules, governance findings, lineage resolution, access policy, or generated artifacts should remain draft until the local gate passes and the relevant risks are documented.

Review feedback is blocking when it identifies:

- A possible weakening of immutable published-contract semantics.
- Missing or incorrect lineage.
- Lowered, omitted, or incorrect classification metadata.
- PII or restricted-field exposure.
- Non-deterministic generated artifacts or registry output.
- Missing tests for compiler, planner, compatibility, lineage, governance, or security behavior.

## 6. CI and Remote Gate Expectations

Remote CI mirrors the local Ruff, test, VS Code, dependency-audit, and
external-smoke gates for the changed surface. It does not replace local
verification for ordinary development.

Recommended CI gate sequence as implementation expands:

```text
format check
mypy baseline ratchet
unit tests
dependency audit
fixture-based compiler tests
lineage, compatibility, and governance regression tests
emitter determinism tests
component smoke tests where applicable
```

CI failures must be investigated from the first failing gate. Agents should not rerun failed CI repeatedly without first reading the failure context.

The Validate workflow starts with a cheap changed-surface detector. Pull request
and push runs execute only the jobs relevant to the files changed in that run;
manual `workflow_dispatch` runs execute every validation job. Changes to the
Validate workflow or its workflow regression tests force every validation job so
CI edits are self-tested.

The CLI job runs strict mypy through
`.github/scripts/check_mypy_baseline.py`. The script compares current mypy
output with `cli/mypy-baseline.txt`: new error lines fail CI, while resolved
lines are reported so the baseline can shrink in the same PR that fixes them.

The OpenMetadata live-smoke CI job must run with
`MODELABLE_OPENMETADATA_TESTCONTAINERS=1` when changes affect the OpenMetadata
export format so the generated artifact is checked against a live OpenMetadata
server stack.

The OpenLineage live-smoke CI job must run with
`MODELABLE_OPENLINEAGE_TESTCONTAINERS=1` when changes affect OpenLineage export
or sync behavior so generated events are posted to a live Marquez-compatible
lineage backend.

The ODCS lint-smoke CI job must run with `MODELABLE_DATACONTRACT_CLI=1` and
`datacontract-cli` available when changes affect the ODCS export format so
generated ODCS artifacts are checked against the upstream validator.

The FHIR Validator CI job must run with
`MODELABLE_FHIR_VALIDATOR=1` and `MODELABLE_FHIR_VALIDATOR_JAR` pointing at the
HL7-maintained `validator_cli.jar` when changes affect the FHIR R4 profile
export format so representative generated R4 `StructureDefinition` profiles are
checked against the upstream validator.

Release changes must also verify package metadata, archive contents, clean-wheel
installation, version agreement, and the manual release dry run. Tag-triggered
publishing uses the protected `pypi` environment and trusted publishing; agents
must not add long-lived package-index credentials to repository secrets.

## 7. Open Decisions

- Whether governance findings become blocking CI failures is an open policy decision. Phase 1 treats them as visibility and process-support findings unless a policy wrapper promotes them to failures.
- The PR template location and required status checks are open until repository hosting configuration is added.

## 8. Release Process

Releases are built from version tags. The tag, Python package, VS Code extension,
changelog, wheel, sdist, VSIX, checksums, and release manifest must agree on the
version.

1. Move user-facing changelog entries from `Unreleased` into a dated release.
2. Set the same version in `cli/pyproject.toml` and `vscode/package.json`.
3. Run the complete local gates in this document and `CONTRIBUTING.md`.
4. Run the release workflow manually; this validates artifacts without publishing.
5. Merge the focused release pull request.
6. Create and push an annotated version tag.
7. Verify PyPI, the GitHub release, checksums, manifest, and VSIX.
8. Install the published wheel in a clean environment and run
   `modelable --version` plus strict sample validation.

PyPI publishing uses trusted publishing through the protected `pypi`
environment. Do not add long-lived package-index credentials. Do not blindly
rerun a failed publication; inspect the first failure and publish a new version
if an immutable artifact already reached the index.

### 1.0 release outcome

Modelable 1.0 is tagged and published. The PyPI publish job uses trusted
publishing through the protected `pypi` environment, repository documentation
uses the 1.0 stable-surface language, and `SECURITY.md` defines the current
1.0.x support policy. The VS Code Marketplace publish job remains disabled
because Marketplace distribution is deferred from the 1.0 surface.

## 9. 1.x Compatibility Policy

Modelable follows semantic versioning within the stable surface defined in
`README.md` and `ROADMAP.md`.

**Additive changes (1.x minor releases):**

- New CLI flags, commands, or output fields that do not change existing
  behavior when not used.
- New generated artifact formats or new emitter options.
- New `.mdl` syntax that is backward-compatible with existing files.
- New diagnostic codes (new errors do not break files that previously passed,
  unless the file was relying on a missing check).

**Breaking changes require a major version bump:**

- Removing or renaming a CLI command, flag, or stable output field.
- Changing the shape of a generated artifact in a way that breaks existing
  consumers (e.g., renaming a Rust struct field, changing a TypeScript import
  path).
- Changing `.mdl` parsing rules that cause previously valid files to fail
  validation.
- Changing compatibility, lineage, or governance report output in a way that
  silently changes findings for existing models.

**Not covered by the stable surface (may change in 1.x):**

- Internal IR types, resolver internals, and private module APIs.
- Language server protocol message shapes (LSP compatibility is maintained
  with VS Code, not with direct LSP clients).
- Experimental or beta-labeled commands and flags.
- Generated artifacts for formats labeled "preview" in the CLI reference.

**Security fixes** are backported to the latest stable minor release. Older
minor versions are not actively patched; upgrade to the latest 1.x.

**Observable conformance** remains the external runtime evidence for
significant emitter or compiler changes. For contributor-accessible conformance,
use the public fixture tracked in issue #107 and documented in
[conformance.md](conformance.md).
