# GitHub Actions and Repository Gap Maintenance Design

**Date:** 2026-06-13  
**Status:** Approved
**Scope:** GitHub Actions version maintenance and reconciliation of confirmed repository-state drift

## Goal

Bring every live GitHub Actions workflow onto the latest stable upstream action releases verified on 2026-06-13, add regression checks for those pins, and correct confirmed documentation and plan-state drift discovered during the repository audit.

## Confirmed Gaps

The audit found five concrete maintenance gaps:

1. `.github/workflows/release.yml` uses obsolete major versions of checkout, Python setup, uv setup, and GitHub release actions.
2. `.github/workflows/validate.yml` uses outdated patch or major versions of checkout, uv setup, and Node setup actions.
3. `cli/tests/test_release_workflow.py` checks only that the release action exists, so action-version regressions are not detected.
4. `README.md` still describes cross-domain compatibility impact as future work although the implementation plan records it as complete.
5. The completed JSON passthrough and TypeScript field-case plans remain in the active plans directory, and the TypeScript plan's task checkboxes were never reconciled after implementation merged.

`docs/cli-tooling-spec.md` also contains an outdated `setup-uv` example and should match the live workflow.

## Action Versions

Use the latest stable releases confirmed from each action's official GitHub release page on 2026-06-13:

| Action | Version |
|---|---|
| `actions/checkout` | `v6.0.3` |
| `actions/setup-python` | `v6.2.0` |
| `actions/setup-node` | `v6.4.0` |
| `astral-sh/setup-uv` | `v8.2.0` |
| `softprops/action-gh-release` | `v3.0.0` |

Exact release tags are preferred over floating major tags because they make workflow changes reviewable and reproducible. GitHub-hosted runners satisfy the Node 24 runtime requirement of the selected action releases.

## Repository Changes

### Workflows

Update every live `uses:` reference in `.github/workflows/release.yml` and `.github/workflows/validate.yml` to the table above. Preserve triggers, permissions, caching, Python and Node versions, commands, and release behavior.

### Regression Tests

Extend workflow text tests so they assert the exact expected action versions in both live workflows. The tests should fail when a workflow silently falls behind the documented baseline.

The tests are intentionally repository-policy checks rather than YAML execution tests. GitHub remains responsible for executing the workflows; local tests ensure the checked-in configuration stays internally consistent.

### Documentation and Plan State

- Update `docs/cli-tooling-spec.md` to use the current `setup-uv` release.
- Update the README milestone table to reflect shipped cross-domain compatibility impact analysis.
- Move the two completed active plans into `docs/superpowers/plans/archived/`.
- Mark the TypeScript field-case plan tasks complete before archiving it so archived state matches the merged implementation.
- Add both plans to the archived plan index.

## Non-Goals

- Adding Ruff, mypy, Pyright, formatting gates, or coverage thresholds.
- Adding Dependabot or Renovate configuration.
- Changing Python, Node, VS Code, package, or runtime dependency versions.
- Refactoring workflow structure or changing release semantics.
- Implementing deferred product features discovered while searching specifications.

These may be worthwhile follow-ons, but combining them with action maintenance would broaden the review and verification surface unnecessarily.

## Verification

Run the repository gates required for workflow, release, documentation, and plan-state changes:

```text
cd cli
uv sync --extra dev --frozen
uv run pytest tests/test_release_metadata.py tests/test_release_workflow.py -v
uv run pytest tests/ --tb=short -q
uv run modelable validate ../samples/mvp --strict

cd ../vscode
npm ci
npm run build
npm test
```

Also run:

```text
git diff --check
git status --short
```

Review the final Markdown and workflow diff for coherent references and verify that no active plan remains solely for already-merged work.

## Risks

- Node 24-based action majors require sufficiently recent runners. The workflows use GitHub-hosted `ubuntu-latest`, which meets that requirement; future self-hosted runners would need separate validation.
- Exact pins require deliberate maintenance for future releases. The added tests make drift visible but do not automate upgrades.
- Moving plans can break links if repository references use their old active paths. Search and update live references as part of the move.

## Success Criteria

- Every live workflow action uses the verified latest stable release.
- Tests enforce those exact action versions.
- Live documentation no longer contradicts shipped compatibility behavior.
- Completed implementation plans are archived and indexed.
- The CLI and VS Code local gates pass without generated or transient artifacts entering the change set.
