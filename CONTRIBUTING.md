# Contributing to Modelable

Contributions that improve correctness, documentation, diagnostics,
interoperability, and generated output are welcome.

## Before you start

- Search existing issues before opening a new one.
- Open an issue before large changes or changes to the `.mdl` language.
- Keep pull requests focused on one coherent change.
- Do not weaken immutable published-version semantics or remove governance
  metadata without an explicit design decision.

## Development setup

The CLI requires Python 3.14 and uses `uv`. Python 3.14 is intentional: the
compiler and validation stack rely on current Pydantic v2 behavior and modern
typing semantics, and CI runs the same Python floor.

```powershell
cd cli
uv sync --extra dev
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --tb=short
uv run modelable validate ../samples/mvp --strict
```

Strict mypy is enforced in GitHub as a baseline ratchet. The repository-wide
baseline is not yet clean, so the gate fails only when a change introduces
errors beyond `cli/mypy-baseline.txt`. When touching typed Python code, run the
same check locally:

```powershell
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

The VS Code extension requires Node.js 26:

```powershell
cd vscode
npm ci
npm run build
npm test
```

Docker is required for generated-language compiler smoke tests.

## Development Flow and Gates

To maintain quality and stability, all contributions must pass through the
following gates:

1. **Local CI**: Before opening a pull request, you must run the local gate
   commands (see [Development setup](#development-setup)). Run the non-mutating
   `ruff check .` and `ruff format --check .` commands after applying fixes so
   the final working tree is verified with the same checks used by CI. Any
   changed code must pass all tests locally.
2. **GitHub Verification**: All pull requests must pass the automated GitHub
   Actions CI before they can be merged. The Validate workflow is split by
   changed surface, so GitHub runs the CLI, VS Code, and external-smoke jobs
   relevant to the files changed in the PR. Verify that all required status
   checks are green on the PR.
3. **Dependency Freshness**: Keep project dependencies up to date with their
   latest stable versions. When adding or updating dependencies, ensure you
   are using the latest compatible versions available.
4. **Compatibility**: Maintain backward compatibility within major versions.
   Breaking changes to the `.mdl` language, IR, or CLI behavior require an
   explicit design decision and a major version bump for the tools.
 5. **Testing**: Add or update tests for any change. Prefer tests that assert
    user-visible behavior, generated artifacts, workflow policy, or public
    contracts instead of private implementation shape. If your change affects the
    IDL or CLI behavior, you must add compatibility tests to verify that
    existing models and workflows remain functional.
 6. **Changelog**: Add a user-facing `CHANGELOG.md` entry under `## [Unreleased]`
    for any change that affects users (new features, changed behavior, fixed
    bugs, dependency bumps, or removed capability). Use the sub-headings
    already present in the `Unreleased` section; internal-only or purely
    mechanical changes (formatting, test-only churn, docs-only fixes with no
    user impact) may omit it, but when in doubt add the entry. This keeps the
    changelog current so a release never requires retrofitting entries at tag
    time.

## Shipping a new feature without leaving a gap

Most of the "fix: close X gap" commits in this repo's history are a feature
that shipped against its happy path and was found to silently misbehave
somewhere else later — a target it didn't cover, an input shape it didn't
validate, a diagnostic that got dropped in one surface but not another. The
project already has the mechanisms to catch this before merge; the failure
mode is not applying them consistently. When adding or changing a
user-visible capability, work through this list rather than only the tests
for the case you had in mind:

1. **Register it in the capability manifest.** Add or update a `Capability`
   entry in `cli/src/modelable/capabilities.py` with an honest
   `CapabilityStatus` (`implemented`, `experimental`, `deferred`,
   `candidate`, or `removed`) and at least one `test_refs` entry pointing at
   a real test. `test_capability_manifest_linkage.py` enforces that the
   reference exists — don't claim `implemented` for a case you haven't
   proven. `modelable capabilities` is the single source of truth for
   support status; if docs prose would say something different, the docs are
   wrong, not the manifest.
2. **Never let parsed input silently no-op.** If the grammar/IR accepts a
   construct the compiler can't fully act on yet, it must produce an
   explicit diagnostic (see `validation/deferred_syntax.py`'s `DEFERRED`
   pattern), not disappear. Per `ROADMAP.md`'s interleaving rule 2, silently
   dropped or ignored parsed content is a release blocker for that
   construct — treat it as such in review, not as a follow-up ticket.
3. **Add a shared conformance fixture, not just a local unit test.**
   Anything reachable from more than one surface (native CLI, browser/Pyodide
   compiler, LSP, Playground) needs a fixture under `cli/tests/conformance/`
   exercised through each surface it touches, per the Slice G3 pattern.
   Tranche 1 of that work found a real bug precisely this way: a diagnostic
   that worked in the CLI was invisible in the browser because
   `workspace.py`'s `synchronize()` only read one of two fields. A
   same-surface-only test would not have caught it.
4. **Hold new emitters/importers to the real-data bar before calling them
   stable.** Interleaving rule 6: a new target isn't stable until
   representative real-world fixture data is covered by deterministic
   regression tests, not just a hand-written minimal case. Hand-written
   fixtures are fine for early development; they are not sufficient to flip
   a capability's status to `implemented`.
5. **If it touches compatibility semantics, prove the negative case.** A
   confirmed false compatibility result is a release blocker (interleaving
   rule 1). Add a test in `compat/diff.py`/`compat/checker.py` coverage that
   shows the change is correctly classified as breaking, not just that the
   compatible case passes.
6. **Changelog and, where relevant, roadmap.** Add the `CHANGELOG.md` entry
   (see gate 6 above) and, if the change closes or partially closes an item
   tracked in `ROADMAP.md`, update that item in the same PR so the roadmap
   doesn't drift from what's actually shipped.

None of this replaces normal code review — it's the specific checklist for
the failure mode this project keeps hitting: a feature that works when used
the way its author tested it, and breaks on the first real use that wasn't.

## Pull requests

A pull request should explain the intent, affected behavior, verification
commands, compatibility or governance risk, and any deferred work. Add tests
for changes to parsing, validation, planning, compatibility, lineage,
governance, runtime behavior, or generated artifacts.

Run the relevant focused tests first, followed by the complete local gate.
Generated output and local build artifacts should not be committed unless the
repository already treats them as reviewed source.

By contributing, you agree that your contribution is licensed under the
Apache License 2.0.

## Conduct and security

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and the
[Project Governance](GOVERNANCE.md). Report
security vulnerabilities through GitHub's private vulnerability reporting,
as described in [SECURITY.md](SECURITY.md), rather than in a public issue.
