# Contributing to Modelable

Modelable is in public alpha. Contributions that improve correctness,
documentation, diagnostics, interoperability, and generated output are
welcome.

## Before you start

- Search existing issues before opening a new one.
- Open an issue before large changes or changes to the `.mdl` language.
- Keep pull requests focused on one coherent change.
- Do not weaken immutable published-version semantics or remove governance
  metadata without an explicit design decision.

## Development setup

The CLI requires Python 3.14 and uses `uv`:

```powershell
cd cli
uv sync --extra dev
uv run ruff check . --fix
uv run ruff format .
uv run mypy .
uv run pytest tests/ --tb=short
uv run modelable validate ../samples/mvp --strict
```

The VS Code extension requires Node.js 24:

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
   commands (see [Development setup](#development-setup)). Any changed code
   must pass all tests locally.
2. **GitHub Verification**: All pull requests must pass the automated GitHub
   Actions CI before they can be merged. Verify that all status checks are
   green on the PR.
3. **Dependency Freshness**: Keep project dependencies up to date with their
   latest stable versions. When adding or updating dependencies, ensure you
   are using the latest compatible versions available.
4. **Compatibility**: Maintain backward compatibility within major versions.
   Breaking changes to the `.mdl` language, IR, or CLI behavior require an
   explicit design decision and a major version bump for the tools.
5. **Testing**: Add or update tests for any change. If your change affects the
   IDL or CLI behavior, you must add compatibility tests to verify that
   existing models and workflows remain functional.

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
