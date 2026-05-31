# Release Pipeline Design

**Date:** 2026-05-31  
**Status:** Draft for review  
**Scope:** Reproducible release pipeline for the `cli/` package and GitHub release assets

## Goal

Create a release pipeline that turns the current `cli/` project into a shippable artifact source with two outputs:

1. A publishable Python package built from the `cli/` project.
2. GitHub release assets that carry the same build outputs and verification metadata.

The release pipeline must be reproducible, deterministic, and anchored to repository state rather than ad hoc local builds.

## Non-Goals

- Introducing a new runtime or deployment system.
- Changing the Modelable source-of-truth semantics.
- Adding package-signing or provenance attestation infrastructure beyond deterministic build metadata.
- Publishing to multiple package indexes in the first slice.
- Reworking the `cli/` package layout unless the packaging step requires a narrow fix.

## Context

The repository already has:

- A Python CLI package under `cli/` using `uv` and Hatchling.
- A local test gate for the CLI and companion VS Code smoke suite.
- Multiple generated artifact emitters that are intentionally deterministic.
- Existing documentation for the CLI commands and governance rules.

The missing piece is a release-oriented build path that produces reusable artifacts from clean repository state and makes those artifacts easy to consume outside the development checkout.

## Recommended Approach

Use a staged release pipeline.

### Why this approach

- It keeps packaging and publishing reproducible without requiring every distribution decision up front.
- It lets the release workflow validate the package in the same environment it builds it.
- It supports GitHub release assets immediately and leaves package-index publication as a controlled final step.

### Alternative approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| Minimal release build | Fastest to ship, but it does not formalize packaging checks or release metadata. | Rejected. |
| Staged release pipeline | Builds, verifies, packages, and uploads artifacts in a controlled sequence. | Chosen. |
| Full automation | Adds version bumping, changelog automation, signing, and package-index publication in one step. | Deferred. |

## Pipeline Shape

The release pipeline should be a GitHub Actions workflow, triggered by either:

- a tagged release commit, or
- a manual workflow dispatch for release candidates.

The workflow should:

1. Check out the repository at the tagged commit.
2. Set up the Python toolchain expected by `cli/`.
3. Install the `cli/` project from the repository using the existing `uv`-based workflow.
4. Run the release gate:
   - targeted CLI unit tests for packaging-related behavior,
   - `uv run pytest tests/ -v` from `cli/`,
   - `uv run modelable validate ../samples/mvp --strict`.
5. Build the Python package artifacts:
   - wheel
   - sdist
6. Generate release metadata:
   - artifact checksums,
   - a machine-readable manifest with package name, version, commit SHA, and build timestamp,
   - a short human-readable release note summary.
7. Upload the built artifacts as GitHub release assets.
8. Publish the package to a configured package index if credentials and target settings are present.

If package-index credentials are absent, the workflow should still produce the GitHub release assets and fail only if the publish step was explicitly requested.

## Artifact Contract

The release pipeline should produce the following files from a single build:

- `modelable-<version>-py3-none-any.whl`
- `modelable-<version>.tar.gz`
- `SHA256SUMS`
- `release-manifest.json`

### Manifest contents

`release-manifest.json` should include:

- package name
- package version
- git commit SHA
- git tag, if present
- build timestamp in UTC
- Python version used for the build
- wheel filename and checksum
- sdist filename and checksum
- whether package publication was attempted
- whether package publication succeeded

The manifest is a release artifact, not a source-of-truth record. Its structure and artifact binding must be deterministic for the same source commit and build inputs; the UTC build timestamp is the only field expected to vary between runs.

## Versioning Rules

- The package version should come from the existing `cli/` package metadata.
- The release workflow must not mutate version numbers automatically in the first slice.
- If the version in the package metadata and the git tag disagree, the workflow should fail with a clear error.
- Release artifacts must be tied to exactly one commit.

## Validation Rules

The release workflow should fail if:

- the `cli/` tests fail,
- the MVP validation command fails,
- wheel or sdist build fails,
- the artifact checksum step fails,
- the package metadata version does not match the release tag,
- the package publish step is requested but cannot authenticate.

The workflow should not try to compensate for release-time failures by mutating source files or rebuilding from an altered working tree.

## Repository Changes Needed

The first implementation slice should add:

- A new release workflow under `.github/workflows/`.
- A small release helper in `cli/` or `scripts/` for packaging metadata and checksums, if the workflow would otherwise duplicate logic.
- Documentation updates in `docs/README.md`, `docs/agent-governance.md`, and `README.md` describing the release path and the required local gate.
- Tests for any new release metadata helper or packaging-specific behavior.

The release pipeline should avoid broad refactors in the same slice.

## Testing Strategy

The local gate for the release slice should include:

- `git status --short`
- review of the workflow and helper diff
- `uv sync --extra dev`
- targeted tests for the release helper or packaging metadata logic
- `uv run pytest tests/ -v`
- `uv run modelable validate ../samples/mvp --strict`
- `git diff --check`

If the workflow introduces package build logic, the release helper should be tested independently from GitHub Actions so the release path remains debuggable locally.

## Risks

- Release automation can drift from the actual package metadata if version checks are not explicit.
- Package publishing introduces a new failure mode if secrets or target settings are misconfigured.
- GitHub release assets can become stale or misleading if the manifest does not bind them to a commit and version.
- Over-automation could hide release-state mistakes if the workflow silently retries or mutates metadata.

## Open Decisions

- Which package index should be the default publish target, if any.
- Whether the release workflow should publish to the package index automatically on tags or only on manual approval.
- Whether the manifest should include a detached signature in a later slice.
- Whether prerelease tags should produce GitHub prereleases or standard releases.

## Success Criteria

This design is complete when the repository can:

- build the `cli/` package from a clean checkout,
- attach the wheel, sdist, checksums, and manifest to a GitHub release,
- optionally publish the same package to a configured package index,
- and verify the release pipeline with local gates that are consistent with the rest of the repository.
