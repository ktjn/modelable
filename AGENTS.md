# Modelable — Agent Instructions

## Before every commit

Run these three commands from the `cli/` directory. All must pass cleanly before pushing.

```bash
uv run ruff format .
uv run ruff check .
uv run pytest --tb=short
```

`ruff format` auto-fixes formatting in place. Run it first, then check, then test.
