# Agent Instructions

## Scope

These instructions apply to the entire repository.

This repository currently contains the Modellable system specification, centered on `docs/modellable-system-spec.md`. Treat that specification as the product source of truth unless the user explicitly changes direction.

## Repository Shape

- `docs/` contains system and product specifications, research, and plans.
- There is no application source tree yet.
- There are no checked-in package manifests, build scripts, or test runners yet.
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

## Future Code Changes

When source code is added:

- Treat `docs/agent-governance.md` as the standing workflow for coding work, including local gates, test gates, PR handling, and verification evidence.
- Add or update tests for behavior that affects validation, compatibility checks, lineage, planning, runtime execution, security, or generated artifacts.
- Keep registry, compiler/planner, runtime, materializer, and adapter concerns separated unless an existing local pattern says otherwise.
- Validate definitions before runtime where feasible.
- Do not expose PII, sensitive, restricted, or unauthorized fields in projections, generated artifacts, logs, or dead-letter payloads.
- Make lineage and compatibility behavior deterministic and testable.
- Keep generated artifacts reproducible and avoid committing transient build output unless the repo establishes that convention.

## Agent Governance

Agents working in this repository must treat `docs/agent-governance.md` as the operating policy for repository changes now and when coding starts. The short form is:

- Preserve the product source of truth in `docs/modellable-system-spec.md`.
- Keep planning, runtime, materializer, registry, adapter, and governance changes separated unless a spec explicitly joins them.
- Use small, reviewable changes with explicit verification evidence.
- Do not claim test coverage, compatibility, lineage, governance, or generated artifact behavior without running the relevant gate or documenting why it is unavailable.
- Surface any change that weakens immutable published-contract semantics as a blocking issue before editing.

## Test Gates

No universal test runner exists yet. Until one is introduced, use the gate that matches the touched surface:

- **Documentation-only:** Review the Markdown diff, check internal links and references, and confirm terminology remains consistent with the system spec.
- **IDL samples or `.mdl` fixtures:** Run the available parser/compiler validation command once the CLI exists; before then, manually check samples against the grammar and examples in `docs/idl-design-spec.md`.
- **Compiler, planner, compatibility, lineage, governance, or emitters:** Run focused unit tests for the changed module and the full local CLI gate once package manifests are present.
- **Runtime, adapter, materializer, or security behavior:** Run focused unit tests plus any integration or smoke gate defined for that component.

When package manifests or scripts are added, update this section with exact commands instead of relying on categories.

## Local Gate

Before reporting completion, run the local gate appropriate to the current repository state:

1. Check `git status --short`.
2. Inspect the changed-file diff.
3. Run the relevant commands from the test gate section.
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

No project-specific build, lint, or test commands are currently defined.

Before claiming verification, inspect the repository for newly added manifests or scripts and run the relevant commands. If only documentation changes were made, a reasonable verification is to review the Markdown diff and confirm links or references are coherent.

## Git Hygiene

- Check `git status --short` before editing and before reporting completion.
- Do not revert user changes.
- Keep commits focused if the user asks you to commit.
- Avoid committing local artifacts such as `node_modules/`, `target/`, `dist/`, test result folders, `.env.local`, `.worktrees/`, fetched Helm dependencies, and Python cache directories.

