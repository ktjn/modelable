# Engineering Improvement Roadmap

This document tracks repository-health and tooling improvements: gaps found
by direct code and CI inspection rather than product feature requests. It
complements [ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md),
which tracks product-facing features. Nothing here is committed until it has
an issue and an accepted design, per the same policy as the product roadmap.

Findings are ranked by impact within each section. "Evidence" cites the exact
file so a reader can verify the claim without re-deriving it.

## Correctness and reliability

### 1. `mypy --strict` is enforced as a baseline ratchet

**Evidence:** `cli/pyproject.toml` sets `[tool.mypy] strict = true`, and the
Validate workflow now runs
`.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run
mypy src/modelable --no-error-summary --show-error-codes` from the `cli/`
directory. The initial `cli/mypy-baseline.txt` captures the current strict
baseline so new error lines fail CI while existing debt remains visible.

**Impact:** Type regressions can no longer land silently on changed CLI
surfaces. The gate also reports resolved baseline lines, so typing cleanup can
shrink the baseline incrementally without requiring the repository to become
fully strict-clean in one large change.

**Remaining work:** Burn down the baseline by module, starting with high-churn
parser, importer, and emitter paths. When the baseline reaches zero, replace
the ratchet wrapper with a direct `uv run mypy src/modelable` CI step and
delete `cli/mypy-baseline.txt`.

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

## Out of scope for this document

Product-facing feature gaps (VS Code Marketplace publishing, remote
tracked-spec polling, distributed registry sync, runtime materialization,
live OpenMetadata sync) are already tracked in
[ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) and are
not duplicated here.
