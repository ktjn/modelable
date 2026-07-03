# Engineering Improvement Roadmap

This document tracks repository-health and tooling improvements: gaps found
by direct code and CI inspection rather than product feature requests. It
complements [ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md),
which tracks product-facing features. Nothing here is committed until it has
an issue and an accepted design, per the same policy as the product roadmap.

Findings are ranked by impact within each section. "Evidence" cites the exact
file so a reader can verify the claim without re-deriving it.

## Correctness and reliability

### 1. `mypy --strict` is configured but not enforced anywhere

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

## Test and coverage visibility

### 2. CI publishes CLI coverage visibility without enforcing a threshold

**Evidence:** `cli/pyproject.toml` declares `pytest-cov` as a dev dependency
and configures `[tool.coverage.run] source = ["src/modelable"]`.
`validate.yml`'s `cli` job now runs `uv run pytest --tb=short
--cov=modelable --cov-report=term-missing --cov-report=xml` and uploads
`cli/coverage.xml` as the `cli-coverage-xml` artifact.

**Impact:** PRs now have a concrete coverage artifact and terminal coverage
summary for the Python package, which makes under-tested compatibility,
lineage, and governance paths easier to spot. This intentionally stops short
of a hard percentage gate while the suite is still being broadened.

**Remaining work:** Decide whether coverage should become a ratcheted signal
after the artifact has enough history. A future threshold should be tied to
critical-path coverage rather than an arbitrary repository-wide percentage.

## Dependency management

### 3. Dependabot routine groups are explicit version-update groups

**Evidence:** `.github/dependabot.yml` keeps one routine group per ecosystem
for Python, VS Code, and GitHub Actions updates, but each group now declares
`applies-to: version-updates` before `patterns: ["*"]`.

**Impact:** Routine dependency churn remains grouped for review efficiency,
while the file documents that those groups are for version updates rather
than vulnerability remediation. Security updates can be handled as their own
Dependabot security-update PRs instead of being mixed into unrelated weekly
version bumps.

**Remaining work:** If security-update volume grows, add an explicit
security-update policy with narrower package patterns or labels. The current
configuration is deliberately simple until there is real update volume to
tune against.

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

## Out of scope for this document

Product-facing feature gaps (VS Code Marketplace publishing, remote
tracked-spec polling, distributed registry sync, runtime materialization,
live OpenMetadata sync) are already tracked in
[ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) and are
not duplicated here.
