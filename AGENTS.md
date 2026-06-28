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
