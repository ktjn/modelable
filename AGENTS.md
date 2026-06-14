# Agent Instructions

## Current State (updated 2026-05-31)

The Phase 1 local modelling compiler is complete. Before starting any task, run `git log --oneline -10`, inspect open issues, and check `ROADMAP.md` plus the relevant product specification for the next open slice.

| Milestone | Status |
|---|---|
| 0 — Tooling baseline | Complete |
| 1 — Parser, IR, validate | Complete |
| 2 — Registry graph, resolver | Complete — lineage edges, compatibility reports, and access policies are populated |
| 3 — Planner, auto projections, CEL, lineage | Complete — auto projections, CEL validation, lineage extraction, plan docs all done |
| 4 — Compatibility and governance | Complete — single-domain compatibility diff shipped; broader compatibility follow-on is available if needed |
| 5 — Emitters | Complete — JSON Schema, Markdown, TypeScript, C#, Java, Python, Rust, and Go are implemented |
| 6 — CLI workflows | Complete |
| 7 — Hardening | Complete |

**Next task:** Use the roadmap, open issues, and relevant product specification to identify the next open slice before starting implementation work.

### Verify current state before coding

```bash
cd cli
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --tb=short -q
uv run modelable validate ../samples/mvp

cd ..\vscode
npm ci
npm run build
npm test
```

---

## Scope

These instructions apply to the entire repository.

This repository currently contains the Modelable system specification, centered on `docs/modelable-system-spec.md`. Treat that specification as the product source of truth unless the user explicitly changes direction.

## Repository Shape

- `docs/` contains system and product specifications, research, and plans.
- `cli/` contains the Python Modelable CLI, parser, IR transformer, compiler orchestration, semantic validation, tests, and package manifest.
- `samples/` contains `.mdl` scenario samples.
- `cli/pyproject.toml` and `cli/uv.lock` define the current Python package and test environment.
- The `.gitignore` already anticipates future frontend, Rust, Docker/Helm, and script artifacts, but those tools are not present in the repo yet.

## Working Principles

- Preserve the spec's domain language: domain-owned canonical models, immutable versions, projections, subscriptions, adapter bindings, planner/runtime/materializer, compatibility, lineage, and governance.
- Do not weaken published-contract semantics. Published model and projection versions are immutable; incompatible changes require new versions.
- Keep adapter-specific concerns separate from platform-neutral model and projection definitions.
- Prefer explicit derivation and traceability over implicit behavior.
- When adding implementation details, align with the MVP scope and call out any decision that touches the open design decisions section.
- Do not introduce broad architecture or tooling churn unless it directly supports the current task.

## Documentation Changes

- Keep Markdown readable and structurally consistent with the existing spec.
- Use fenced code blocks with language identifiers for examples, such as `yaml`, `json`, `text`, or `sql`.
- Keep examples internally consistent with the terms and fields already used in the spec.
- When adding requirements, classify them clearly as MVP, deferred, non-goal, or open decision when applicable.
- Avoid adding implementation commitments that contradict the platform-neutral design unless the user explicitly asks to narrow the design.
- If a change affects agent workflow, test policy, PR policy, or local verification expectations, update `docs/agent-governance.md`.

## Code Changes

- Treat `docs/agent-governance.md` as the standing workflow for coding work, including local gates, test gates, PR handling, and verification evidence.
- When selecting or adding frameworks, libraries, CLIs, build tools, or scaffolding commands, validate the current latest stable version and current recommended usage with a web search against official documentation, package registries, or release pages at the time of the work. Do not rely on agent training data or remembered version knowledge for "latest" choices.
- Prefer the latest stable framework and tool versions unless the specification, compatibility constraints, existing project manifests, or an explicit user instruction require a different version. Document any deliberate pin to an older version in the handoff or PR notes.
- For Python projects, use `uv` for Python version management, project setup, dependency management, lockfile generation, and Python tool execution unless the user explicitly asks for another tool or an existing project convention requires it.
- Add or update tests for behavior that affects validation, compatibility checks, lineage, planning, runtime execution, security, or generated artifacts.
- Add Docker-backed compile smoke tests for any change that adds or modifies a generated-language backend or generated artifact format, using the latest official compiler/runtime image for each affected language.
- Keep registry, compiler/planner, runtime, materializer, and adapter concerns separated unless an existing local pattern says otherwise.
- Validate definitions before runtime where feasible.
- Do not expose PII, sensitive, restricted, or unauthorized fields in projections, generated artifacts, logs, or dead-letter payloads.
- Make lineage and compatibility behavior deterministic and testable.
- Keep generated artifacts reproducible and avoid committing transient build output unless the repo establishes that convention.

## Agent Governance

Agents working in this repository must treat `docs/agent-governance.md` as the operating policy for repository changes now and when coding starts. The short form is:

- Preserve the product source of truth in `docs/modelable-system-spec.md`.
- Keep planning, runtime, materializer, registry, adapter, and governance changes separated unless a spec explicitly joins them.
- Use small, reviewable changes with explicit verification evidence.
- Do not claim test coverage, compatibility, lineage, governance, or generated artifact behavior without running the relevant gate or documenting why it is unavailable.
- Surface any change that weakens immutable published-contract semantics as a blocking issue before editing.

## Test Gates

Use the gate that matches the touched surface:

- **Documentation-only:** Review the Markdown diff, check internal links and references, and confirm terminology remains consistent with the system spec.
- **IDL samples or `.mdl` fixtures:** Run `uv run modelable validate <path>` from `cli/` for the touched fixture or sample when it is expected to be supported by the current parser/compiler; otherwise manually check samples against the grammar and examples in `docs/idl-design-spec.md` and state why CLI validation is not yet applicable.
- **Parser, IR, semantic validation, compiler, or CLI:** Run focused tests for the changed module from `cli/`, then run `uv run pytest tests/ -v`.
- **Compiler, planner, compatibility, lineage, governance, or emitters:** Run focused unit tests for the changed module and the full local CLI gate.
- **Runtime, adapter, materializer, or security behavior:** Run focused unit tests plus any integration or smoke gate defined for that component.

## Local Gate

Before reporting completion, run the local gate appropriate to the current repository state:

1. Check `git status --short`.
2. Inspect the changed-file diff.
3. For CLI changes, run `uv run ruff check .` and
   `uv run ruff format --check .` from `cli/` before the relevant tests.
4. For documentation-only changes, verify the Markdown diff is coherent and no referenced document is missing.
5. Report commands run and any skipped gate with the reason.

Do not substitute remote CI for the local gate unless the user explicitly asks for CI-only handling.

## Pull Request Handling

When asked to prepare or update a PR:

- Keep the PR focused on one coherent change.
- State the user-visible intent, touched documents or modules, and verification evidence in the PR body.
- Call out any skipped gate, deferred requirement, open design decision, or compatibility risk.
- Do not include generated artifacts unless the repository has established that they are reviewed outputs.
- If review feedback concerns published-contract semantics, governance findings, lineage determinism, or PII exposure, treat it as blocking until resolved or explicitly accepted by the user.
- Prefer draft PRs for incomplete design or implementation work.

## Commands

Current CLI commands are run from `cli/`:

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ -v
uv run modelable validate tests/fixtures/customer.mdl
```

Strict mypy is configured for incremental typing work but is not a required
gate until the existing repository-wide error baseline is resolved.

Before claiming verification, inspect the repository for newly added manifests or scripts and run the relevant commands. If only documentation changes were made, a reasonable verification is to review the Markdown diff and confirm links or references are coherent.

## Git Hygiene

- Check `git status --short` before editing and before reporting completion.
- Do not revert user changes.
- Keep commits focused if the user asks you to commit.
- Avoid committing local artifacts such as `node_modules/`, `target/`, `dist/`, test result folders, `.env.local`, `.worktrees/`, fetched Helm dependencies, and Python cache directories.

