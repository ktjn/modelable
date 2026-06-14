# Agent Governance

This document defines how automated and human-assisted agents operate within the
[Project Governance](../GOVERNANCE.md). It is process guidance for agents, not
product semantics. The product source of truth remains
[modelable-system-spec.md](modelable-system-spec.md).

## 1. Purpose

Agent governance exists to keep repository changes reviewable, locally
verifiable, and aligned with Modelable's core contract guarantees and
[Product Principles](../GOVERNANCE.md#3-product-principles-in-governance):

- Published model and projection versions are immutable.
- Incompatible changes require new versions.
- Lineage, compatibility, governance findings, and generated artifacts must be deterministic.
- Adapter-specific details must not leak into platform-neutral model and projection definitions.
- PII, restricted fields, and unauthorized fields must not be exposed through projections, generated artifacts, logs, or dead-letter payloads.

These rules apply to documentation, samples, future source code, tests, generated artifacts, CI configuration, and PR preparation.

## 2. Agent Operating Rules

Agents must:

- Consult [AGENTS.md](../AGENTS.md) for the current project state and [ROADMAP.md](../ROADMAP.md) for planned work before starting.
- Read the relevant specification before editing.
- Keep changes small enough for meaningful review.
- Add or update tests with any code change that affects parser behavior, validation, compatibility checks, lineage, planning, runtime execution, governance, security, or generated artifacts.
- Add Docker-backed compile smoke tests for any change that adds or modifies a generated-language backend or generated artifact format, using the latest official compiler/runtime image for each affected language.
- Do not use hard-coded line numbers to locate language elements in test fixtures or sample files. Derive line positions dynamically.
- Validate current latest stable framework, library, CLI, build-tool, and scaffolding choices with a web search against official documentation, package registries, or release pages before adding or changing them.
- Use the latest stable framework and tool versions by default, unless the specification, compatibility constraints, existing manifests, or explicit user direction require a different version.
- Record any deliberate use of an older framework or tool version in the final handoff or PR body.
- Use `uv` exclusively for Python version management, project setup, dependency management, lockfile generation, and tool execution. Keep packages up to date with the latest stable versions.
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
uv run mypy .
uv run pytest tests/ -v
uv run modelable validate tests/fixtures/customer.mdl
```

Run these commands from `cli/`. No formatter or static-analysis command is configured yet; if one is added, update this section and `AGENTS.md` with the exact command. **If a milestone is completed, update the status table in [AGENTS.md](../AGENTS.md).**

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
| LSP, VS Code extension, or editor integration | Focused LSP tests plus `cd vscode && npm ci && npm run build && npm test` |
| Release pipeline or packaging metadata | Focused release metadata/workflow tests plus the full local CLI gate |
| Runtime, subscriptions, adapters, or materializers | Unit tests, integration or smoke tests for the adapter boundary, and failure-mode coverage |
| Security, permissions, PII, or restricted fields | Negative tests proving unauthorized exposure is rejected or reported as a governance finding |

Compatibility, lineage, and governance tests must include negative cases when behavior can fail unsafely.

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

Remote CI should eventually mirror the local gate. It should not replace local verification for ordinary development.

Recommended CI gate sequence as implementation expands:

```text
format check
static analysis or type check
unit tests
fixture-based compiler tests
lineage, compatibility, and governance regression tests
emitter determinism tests
component smoke tests where applicable
```

CI failures must be investigated from the first failing gate. Agents should not rerun failed CI repeatedly without first reading the failure context.

Release changes must also verify package metadata, archive contents, clean-wheel
installation, version agreement, and the manual release dry run. Tag-triggered
publishing uses the protected `pypi` environment and trusted publishing; agents
must not add long-lived package-index credentials to repository secrets.

## 7. Open Decisions

- Exact formatter and static-analysis commands are open until those tools are configured.
- Whether governance findings become blocking CI failures is an open policy decision. Phase 1 treats them as visibility and process-support findings unless a policy wrapper promotes them to failures.
- The PR template location and required status checks are open until repository hosting configuration is added.
