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

## Future Code Changes

When source code is added:

- Add or update tests for behavior that affects validation, compatibility checks, lineage, planning, runtime execution, security, or generated artifacts.
- Keep registry, compiler/planner, runtime, materializer, and adapter concerns separated unless an existing local pattern says otherwise.
- Validate definitions before runtime where feasible.
- Do not expose PII, sensitive, restricted, or unauthorized fields in projections, generated artifacts, logs, or dead-letter payloads.
- Make lineage and compatibility behavior deterministic and testable.
- Keep generated artifacts reproducible and avoid committing transient build output unless the repo establishes that convention.

## Commands

No project-specific build, lint, or test commands are currently defined.

Before claiming verification, inspect the repository for newly added manifests or scripts and run the relevant commands. If only documentation changes were made, a reasonable verification is to review the Markdown diff and confirm links or references are coherent.

## Git Hygiene

- Check `git status --short` before editing and before reporting completion.
- Do not revert user changes.
- Keep commits focused if the user asks you to commit.
- Avoid committing local artifacts such as `node_modules/`, `target/`, `dist/`, test result folders, `.env.local`, `.worktrees/`, fetched Helm dependencies, and Python cache directories.

