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

### 2. CI enforces a per-critical-path coverage ratchet, not a repository-wide threshold

**Evidence:** `cli/pyproject.toml` declares `pytest-cov` as a dev dependency
and configures `[tool.coverage.run] source = ["src/modelable"]`.
`validate.yml`'s `cli` job runs `uv run pytest --tb=short --cov=modelable
--cov-report=term-missing --cov-report=xml`, uploads `cli/coverage.xml` as
the `cli-coverage-xml` artifact, and then runs
`.github/scripts/check_coverage_ratchet.py` against
`cli/coverage-baseline.txt` — the same checked-in-baseline pattern the mypy
strict ratchet (finding 1, above) already uses. The baseline lists the 12
files covering Slice G1's eight protection categories from
[docs/correction-and-capability-plan.md](correction-and-capability-plan.md#slice-g1-critical-compatibility-coverage):
model/projection compatibility (`compat/checker.py`, `compat/diff.py`),
dependency resolution (`dependency_graph.py`, `registry/resolver.py`),
expression validation (`expressions/cel.py`, `compiler/workspace.py`),
lineage (`planner/lineage.py`), governance (`governance/checker.py`),
signatures (`registry/signature.py`), and target compatibility
(`emitters/protobuf.py`, `emitters/grpc.py`, `commands/validate_compat.py`).

**Impact:** A PR that drops coverage on any of these specific files fails
CI, closing the gap the previous "remaining work" note here flagged —
critical-path coverage is now a ratcheted signal, tied to the paths that
actually determine compiler correctness rather than an arbitrary
repository-wide percentage. The rest of the codebase keeps the same
visibility-only artifact/terminal-summary behavior as before.

**Remaining work:** Raise individual baseline numbers as their tests improve
(never lower one to make a change pass); add more files to
`coverage-baseline.txt` if a future slice identifies another critical path.

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
