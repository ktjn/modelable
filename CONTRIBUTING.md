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
uv sync --extra dev --frozen
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

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Report
security vulnerabilities through GitHub's private vulnerability reporting,
as described in [SECURITY.md](SECURITY.md), rather than in a public issue.
