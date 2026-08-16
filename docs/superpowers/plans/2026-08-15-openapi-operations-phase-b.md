# OpenAPI Phase B: Paths and Operations Implementation Plan

> Implements the accepted design in
> `docs/superpowers/specs/2026-08-15-openapi-operations-design.md`.

## Goal

Add an explicit, compiler-validated `api` grammar surface and extend the
existing OpenAPI 3.1 emitter with deterministic paths, operations, path
parameters, JSON request bodies, and projection-backed responses.

## Scope

The first slice supports versioned domain-local APIs, `GET`/`POST`/`PUT`/
`PATCH`/`DELETE`, absolute path templates with model-key parameters, one JSON
request body, and numeric projection-backed responses. Security, query/header/
cookie parameters, webhooks, import hardening, and D1-D4 fidelity remain out
of scope.

## Implementation sequence

1. Add parser grammar and IR for `api`, `operation`, and `responses`.
2. Add parser and formatter fixtures covering the accepted syntax.
3. Add semantic validation for model/version resolution, API/operation identity,
   path syntax and key binding, projection references, methods, and status
   codes.
4. Extend OpenAPI emission with paths, parameters, request bodies, responses,
   and operation metadata while reusing Phase A schema mapping.
5. Add deterministic output and invalid-contract regression tests.
6. Add compatibility facts for operation/path/method/response changes.
7. Update language/compiler references, changelog, and archive this plan only
   after the implementation lands.

## Critical files

- `cli/src/modelable/grammar/modelable.lark`
- `cli/src/modelable/parser/ir.py`
- `cli/src/modelable/parser/transformer.py`
- `cli/src/modelable/emitters/openapi.py`
- `cli/src/modelable/operations/compilation.py`
- `cli/tests/`
- `docs/language-reference.md`
- `docs/compiler-reference.md`
- `CHANGELOG.md`

## Verification

From `cli/`, run the focused parser/emitter tests first, then the required
four checks from `AGENTS.md`:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```
