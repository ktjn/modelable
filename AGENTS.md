# Modelable — Agent Instructions

## Before every commit

Run these three commands from the `cli/` directory. All must pass cleanly before pushing.

```bash
uv run ruff format .
uv run ruff check .
uv run pytest --tb=short
```

`ruff format` auto-fixes formatting in place. Run it first, then check, then test.

## Closing issues

When a commit or PR fixes a GitHub issue, include a `Closes #N` line in the commit message or PR body. GitHub will auto-close the issue when the PR is merged.

```
fix: short description

Closes #123
Closes #456
```

## Cutting a release

1. **Bump versions** — update `version` in `cli/pyproject.toml` and `vscode/package.json` to the same new value (e.g. `1.0.1`).
2. **Update CHANGELOG.md** — add a `## [X.Y.Z] - YYYY-MM-DD` section above `## [Unreleased]` with a `### Fixed` / `### Added` / `### Changed` summary of the changes.
3. **Commit** with message `chore: bump version to X.Y.Z`.
4. **Push** to `main`.
5. **Tag and push the tag**:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
   Pushing the tag triggers the CI release workflow, which publishes to PyPI, the VS Code Marketplace, and creates a GitHub release.

Do not manually create the GitHub release — the workflow does it automatically from the tag.
