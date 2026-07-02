# Engineering Improvement Roadmap

This document tracks repository-health and tooling improvements: gaps found
by direct code and CI inspection rather than product feature requests. It
complements [ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md),
which tracks product-facing features. Nothing here is committed until it has
an issue and an accepted design, per the same policy as the product roadmap.

Findings are ranked by impact within each section. "Evidence" cites the exact
file so a reader can verify the claim without re-deriving it.

## Correctness and reliability

### 1. `oci://` registry paths silently no-op instead of failing

**Evidence:** `cli/src/modelable/registry/oci.py` — `OCIRegistry.push()` and
`.pull()` each contain only a `# TODO` comment and a `print(f"... (not
implemented)")`. `cli/src/modelable/registry/factory.py` routes any registry
path beginning with `oci://` to this class, and
`cli/src/modelable/commands/compile.py:70` calls `registry.push(...)`
unconditionally as part of `modelable compile`.

**Impact:** A user who points `--registry` at an `oci://` URL gets a silent
no-op: the command exits successfully, prints a line easy to miss in normal
output, and nothing is pushed or pulled. This is a data-loss-shaped footgun
(the user believes their artifact was published to the registry).

**Suggested fix:** Either implement OCI push/pull, or raise
`NotImplementedError` (or a clear `ModelableError`) from both methods so the
CLI fails loudly instead of pretending to succeed. Add a test asserting the
failure behavior either way.

### 2. `mypy --strict` is configured but not enforced anywhere

**Evidence:** `cli/pyproject.toml` sets `[tool.mypy] strict = true`, but
`mypy` does not appear in `.github/workflows/validate.yml`, and both
`CONTRIBUTING.md` and `docs/maintainers.md` explicitly note the
repository-wide baseline isn't clean yet, so it isn't a required gate.

**Impact:** Type errors can land on `main` indefinitely; the strict config
currently documents an aspiration rather than a checked invariant. A ~22k
line, actively-growing Python codebase without an enforced type gate
accumulates regressions faster than an occasional manual `mypy` run catches
them.

**Suggested fix:** Add a baseline-diff gate rather than an all-or-nothing
switch: snapshot the current error count/set (e.g. via `mypy --strict
--txt-report` or a stored baseline file), and fail CI only when new modules
introduce errors beyond the baseline. Shrink the baseline opportunistically
as modules are touched. This turns "not clean yet" into a ratchet instead of
an indefinitely deferred gate.

### 3. No dependency vulnerability scanning in CI

**Evidence:** No `pip-audit`, `osv-scanner`, `safety`, or similar step exists
in any workflow under `.github/workflows/`. `codeql.yml` covers static
analysis of first-party code but not known-vulnerable third-party
dependencies.

**Impact:** A vulnerable transitive or direct dependency (Python or npm) can
sit unnoticed between Dependabot's weekly cadence and manual awareness.

**Suggested fix:** Add a `pip-audit` (or `uv pip audit` equivalent) step for
`cli/` and an `npm audit --omit=dev` (or equivalent) step for `vscode/` to
`validate.yml`, gated the same way as the other changed-surface jobs.

### 4. CodeQL only runs on manual `workflow_dispatch`

**Evidence:** `.github/workflows/codeql.yml` has `on: workflow_dispatch`
only — no `push`, `pull_request`, or `schedule` trigger.

**Impact:** CodeQL results are only as fresh as the last time someone
remembered to trigger the workflow by hand. In practice this means static
security analysis is effectively not running on an ongoing basis.

**Suggested fix:** Add a `schedule` trigger (e.g. weekly) at minimum;
consider adding `push: branches: [main]` if runtime cost is acceptable.

## Test and coverage visibility

### 5. `pytest-cov` is installed but coverage is never measured in CI

**Evidence:** `cli/pyproject.toml` declares `pytest-cov` as a dev dependency
and configures `[tool.coverage.run] source = ["src/modelable"]`, but
`validate.yml`'s `cli` job runs plain `uv run pytest --tb=short` with no
`--cov` flag, no coverage artifact upload, and no threshold check. A stray
root-level `.coverage` file suggests coverage has been run locally but isn't
tracked.

**Impact:** There is no visibility into which modules are under-tested, and
no regression signal if a change silently drops coverage on a
compatibility-, lineage-, or governance-critical path — exactly the paths
`docs/maintainers.md` says must have tests.

**Suggested fix:** Add `--cov=modelable --cov-report=xml` to the CI test
step and upload the report (Codecov, or a simple job-summary percentage
check) so coverage trends are visible on PRs. A hard minimum-percentage gate
is optional; visibility alone is the main win.

## Dependency management

### 6. Dependabot groups every dependency into one PR per ecosystem

**Evidence:** `.github/dependabot.yml` uses `patterns: ["*"]` for the
`python-dependencies`, `vscode-dependencies`, and `actions` groups, so all
updates for an ecosystem land in a single weekly PR regardless of whether
they're patch, minor, or major, or security-relevant.

**Impact:** A security patch is harder to reason about and merge quickly
when it's bundled with unrelated version bumps; a bad upgrade in one
dependency can block or delay all the others in the same PR, and `git
bisect`-style review of "what changed" is harder.

**Suggested fix:** Keep the grouping for routine patch/minor bumps (it's
reasonable noise reduction), but exclude security updates from the group (or
add a separate ungrouped security-updates rule) so vulnerability fixes ship
independently of routine dependency churn.

## Process notes (lower priority, informational)

- **Python 3.14 floor:** `cli/.python-version` and `requires-python =
  ">=3.14"` pin to a very recent Python release. This is a deliberate,
  documented choice (`docs/maintainers.md` cites Pydantic v2 validation and
  modern typing behavior), so it isn't a defect, but it does raise the bar
  for contributors and CI runners whose Python toolchain/network access
  hasn't caught up yet (encountered directly while preparing this roadmap:
  `uv`'s Python 3.14 download failed in this sandboxed environment). Worth a
  one-line rationale in `CONTRIBUTING.md` so new contributors don't wonder
  why the floor is so high.
- **`registry/oci.py` scope:** if OCI support isn't planned soon, consider
  removing the `oci://` routing from `factory.py` entirely until a real
  implementation exists, rather than shipping a reachable dead code path.

## Out of scope for this document

Product-facing feature gaps (VS Code Marketplace publishing, remote
tracked-spec polling, distributed registry sync, runtime materialization,
live OpenMetadata sync) are already tracked in
[ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) and are
not duplicated here.
