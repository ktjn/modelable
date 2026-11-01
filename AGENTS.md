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

Before pushing, install the versioned hook with `git config core.hooksPath .githooks`
and let it run `.github/scripts/run_browser_playground.py`. Do not push after a
failed or incomplete local gate, and do not bypass it with `--no-verify`.
GitHub Actions runs the browser build only; it is not a substitute for local
validation. `main` must remain protected and PR-only, with the GitHub Build
status check required before merge.

## Codegen output changes

If your change alters what any codegen target emits (a shared rendering
helper, a per-target emitter, `_schema_mapping.py`, etc.), `pytest` will fail
in `tests/test_golden_artifacts.py` with a content diff against
`tests/golden/artifacts/`. If the new output is correct, regenerate and
review the diff like any other generated-artifact change before committing:

```bash
uv run python scripts/write_golden_artifacts.py --output tests/golden/artifacts
```

If the diff is not what you expected, that's the test doing its job — it
means the change touched more than intended. `tests/golden/artifacts/`
holds real generated code (including `.py` files) and is excluded from
`ruff`/formatting in `pyproject.toml`; never hand-edit it or run a formatter
over it directly.

## Plans and specs

Design docs and implementation plans (created via the `writing-plans`/brainstorming workflow) live in `docs/superpowers/specs/` and `docs/superpowers/plans/`. Once a plan's implementation has merged to `main`, move both the plan and any spec it implements into `docs/superpowers/specs/archived/` and `docs/superpowers/plans/archived/` (same filename, just relocated) in the same PR or a prompt follow-up — don't leave completed plans sitting alongside active ones. Only plans/specs for work still in progress (or not yet started) belong in the top-level `plans/`/`specs/` directories.

## System-spec onboarding

- Published tool: `system-spec-ref==0.2.0` (`system-spec`). Install with `uv tool install --index-url https://pypi.org/simple system-spec-ref==0.2.0`; verify `system-spec --version` and [package/export provenance](docs/superpowers/specs/system-spec/evidence/toolkit-pypi-0.2.0.json).
- Follow the intact offline toolkit's [WIRING.md](tools/system-spec/WIRING.md), [CONSTITUTION.md](tools/system-spec/CONSTITUTION.md) and brownfield track [BROWNFIELD.md](tools/system-spec/BROWNFIELD.md).
- Project specifications and acceptance records remain in [docs/superpowers/specs/system-spec/](docs/superpowers/specs/system-spec/README.md). Before committing, validate inventory at `inventory`, active compilation at `verification`, and the unaccepted contract proposal at `architecture`, with `--check-artifacts --root .`; use the exact commands in that README.
- For bounded work, use `system-spec <spec> --context <component-id>` and `--impact <id>`. Source/schema/evidence pins and native gates above remain required; package installation does not establish whole-product conformance or approve the proposal.
- Offline fallback: `uv run --project cli python tools/system-spec/reference-implementation/metamodel.py <spec> --stage <stage>`. The snapshot is pinned by the package receipt; preserve its tree/bytes and follow WIRING.md's fresh-export upgrade procedure.
- Applicable formal/data-model guidance: [TLA+](tools/system-spec/.github/skills/tla/SKILL.md), [Alloy](tools/system-spec/.github/skills/alloy/SKILL.md), [Modelable](tools/system-spec/.github/skills/modelable/SKILL.md). Follow each guide's separate tool prerequisites.
- Report newly discovered facts/model gaps using the exported constitution's self-improvement process and the existing onboarding feedback route. Maintainers own acceptance and unresolved adoption gates.

## Web AI/chat changes

`web/src/ai/**`, `App.tsx`'s conversation wiring, or the Python conversation
engine/plan schema (`cli/src/modelable/llm/conversation_*.py`) each affect
what the playground's real-model chat assistant can do. These aren't covered
by CI or `npm test` — note in your handoff that
`docs/maintainers.md` → "Manual real-model WebLLM chat conformance" should be
run (`npm run test:e2e:manual` from `web/`); it needs real WebGPU hardware,
so run it yourself if you have that, otherwise flag it for the user.

## Changelog updates

Every user-facing change must add a `CHANGELOG.md` entry under the current
`## [Unreleased]` section (use its existing `### Added` / `### Changed` /
`### Fixed` sub-headings) in the same PR as the change. Internal-only changes
(formatting, test-only churn, no-user-impact doc edits) may omit it. Keeping the
changelog current avoids retrofitting entries during a release.

## Closing issues

When a commit or PR fixes a GitHub issue, include a `Closes #N` line in the commit message or PR body. GitHub will auto-close the issue when the PR is merged.

```
fix: short description

Closes #123
Closes #456
```
