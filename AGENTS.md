# Modelable — Agent Instructions

## Before every commit

Run these four commands from the `cli/` directory. All must pass cleanly before pushing.

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

`ruff format` auto-fixes formatting in place. Run it first, then check, then test.

The mypy baseline check is a *ratchet*, not a plain type check: it fails on any error line not already in `mypy-baseline.txt`, matched by exact file:line. If you change line counts above existing errors in a file (e.g. inserting a helper function), their line numbers shift and the ratchet reports them as "new" even though nothing new was actually introduced. Before assuming real new debt, diff the reported errors against the old baseline entries for that file — if the messages match and the total count is unchanged, it's a pure shift: regenerate the baseline (rerun mypy on the whole tree, take only lines containing `: error:`, normalize path separators to `/`, sort, and write back with the file's existing header comment). If the count or messages differ, fix the actual typing issue instead of baselining it.

CI runs all four checks (`validate.yml`); passing pytest locally is not sufficient — always run the other three before pushing.

## Plans and specs

Design docs and implementation plans (created via the `writing-plans`/brainstorming workflow) live in `docs/superpowers/specs/` and `docs/superpowers/plans/`. Once a plan's implementation has merged to `main`, move both the plan and any spec it implements into `docs/superpowers/specs/archived/` and `docs/superpowers/plans/archived/` (same filename, just relocated) in the same PR or a prompt follow-up — don't leave completed plans sitting alongside active ones. Only plans/specs for work still in progress (or not yet started) belong in the top-level `plans/`/`specs/` directories.

## Closing issues

When a commit or PR fixes a GitHub issue, include a `Closes #N` line in the commit message or PR body. GitHub will auto-close the issue when the PR is merged.

```
fix: short description

Closes #123
Closes #456
```
