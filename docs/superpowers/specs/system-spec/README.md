# Modelable system-spec onboarding

- Date: 2026-10-31. Product baseline: `0fead2321bdef11c72b2746eb57f3a8b0e327c94` (Modelable 1.15.1).
- Metamodel baseline: system-specification `00188b037797fd37240dab9a0a11c431815e3ac9`; schema vendored as [schema.json](schema.json). Hashes and environment: [baseline.json](baseline.json).
- Status: whole-product inventory recorded; compilation behavior pinned for the bounded scope below. Whole-product Levels 1â€“3 remain open.
- Live onboarding TODO: inventory and bounded compilation discovery complete; characterization complete with two skips; full dependency/data mapping, symlink coverage, quality criteria, formal assessment and release review remain open.
- This is internal development metadata. Product authority remains [architecture.md](../../../architecture.md), the existing capability catalog and native acceptance gates. No runtime, language, dependencies, installed skills or product commands change.
- `modelable spec` tracks dbt/FHIR/ODCS imports; use system-specification's validator for these files.

## Inventory and discovery

[inventory.yaml](inventory.yaml) registers shipped surfaces and coarse logical dependencies. Draft capabilities and omitted detailed data contracts are deliberate inventory gaps, not verified architecture.

| Surface | Observed entrypoint / source | Persistence and dependencies |
|---|---|---|
| Semantic toolchain | `cli/src/modelable/{compiler,parser,validation,planner,emitters,registry,operations}` | Local workspaces, plans, generated artifacts, registry SQLite, allocation ledgers, optional snapshots; these remain together at coarse inventory granularity. |
| Native CLI | `cli/pyproject.toml` â†’ `modelable.cli:cli`; `bin/modelable*` launchers | Registers compiler, query, registry, dependency, import, integration and optional LLM workflows. Review command-specific side effects before extraction. |
| Language server | `commands/lsp.py` â†’ `lsp/server.py`; stdio | Shared language/semantic engine and native conversation service; in-memory per-workspace indexes and debounced diagnostics. |
| Browser facade | `browser/api.py`, `browser/dispatch.py`, `cli/browser/pyproject.toml` | Same Python semantics through browser DTO/protocol adapters; browser wheel supports Python >=3.14,<3.15. Native package supports >=3.14. |
| Playground | `web/src/main.tsx`, `compiler.worker.ts`, `web/package.json` | Pyodide worker, IndexedDB workspace, service-worker assets; WebLLM/Ollama optional. Source, derived results and AI metadata have different lifetimes. |
| VS Code | `vscode/extension.js`, `vscode/package.json` | Launches configured Python/LSP process; explicit conversation preview/apply boundary. |
| Build/release/docs jobs | `.github/workflows/{validate,docs,release-prep,release-tag,release,codeql}.yml` | Development/delivery units, not deployed product services. Existing gates stay authoritative. |

- External-source names in YAML are categories observed in implementation/integration docs, not configured production endpoints. No live provider, registry, catalog or remote publication was exercised.
- Streaming runtime/materializer are deferred product concepts per architecture Â§Â§7/18, not invented deployable services. No shipped MCP server was found in this checkout.
- `tools/agentbuild` has local environment/cache remnants but no tracked files at this revision. Existing untracked `.agentbuild/` is untouched and outside the product onboarding scope.
- The six inventory components are candidates for bounded discovery, not a claim that technology folders are final consistency boundaries.
- Data discovery still needs compiler IR/workspace/diagnostics; plan v0/v1; registry schema/snapshots/usage/locks; browser source/artifact DTOs and IndexedDB workspace; conversation/audit state. Existing schemas remain authoritative; no public classification is inferred from a missing annotation.

## Bounded compilation contract

[compilation.yaml](compilation.yaml) describes `CompilationService.execute_direct/preview/apply/discard` and five top-level dataclass shapes observed in `cli/src/modelable/operations/compilation.py`.

- The compilation unit groups output artifacts, plans, local registry state, allocation ledgers and conversational audit under the existing staging/promotion/freshness boundary. Do not split those into independent components merely to meet a page or context limit.
- `max_owns_data: 5` is an explicit per-component override preserving that boundary; other context limits retain defaults.
- No fictitious HTTP transport or authentication service is introduced. The interfaces name Python operations and actual local confirmation/filesystem obligations.
- Direct execution and conversational apply differ: direct execution has no conversational audit; apply binds a specific confirmation and checks freshness under locks.
- A post-commit cleanup failure is distinct from a rolled-back promotion. A failing return does not always mean no files changed.
- Types in `fields` reproduce top-level dataclass annotations. Nested types, protocol defaults, helper exceptions and external OCI/descriptor-tool effects still require complete mapping; this is not a replacement generated schema.
- `restricted` is a conservative onboarding handling policy for the five DTOs, **not an observed product classification**. Data may contain user source text, previews and paths; classification review remains open.
- Modeled capability/data versions `1.0` identify this observed contract description, not separately published product APIs. Evidence records the actual source commit, not these numeric model versions.

## Characterization and gate record

Observed run: **221 passed, 2 skipped in 29.35s**, CPython 3.14.5, pytest 9.1.1, Windows. [Output](evidence/characterization.txt) and source/test hashes are retained.

Run from `cli/` with a fresh, unused temp directory (do not point pytest at an existing valuable directory):

```powershell
$onboardingTemp = Join-Path (Get-Location) ('.venv/system-spec-pytest-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest tests/test_compilation_service.py tests/test_identity.py tests/test_plan_protocol.py tests/test_browser_api.py tests/test_capabilities.py tests/test_spec_tracking.py -n 0 -q --tb=short --basetemp=$onboardingTemp -p no:cacheprovider
```

The two skips are the changed-resolved-parent and escaping-directory-symlink cases in `test_compilation_service.py`; Windows directory symlink creation was unavailable. MOD-COMP-10 retains that gap with no passing evidence.

| Requirement | Source characterization in `cli/tests/test_compilation_service.py` |
|---|---|
| MOD-COMP-01 | `test_execute_direct_writes_registry_plans_and_rust_artifacts`, `test_execute_direct_does_not_write_conversational_audit` |
| MOD-COMP-02 | `test_preview_stages_exact_files_without_mutating_workspace` |
| MOD-COMP-03 | `test_apply_rejects_stale_source`, `test_apply_rejects_stage_and_manifest_tampering`, `test_apply_promotes_stage_without_recompiling` |
| MOD-COMP-04 | `test_waiting_apply_rechecks_freshness_under_workspace_lock` |
| MOD-COMP-05 | `test_audit_promotion_failure_rolls_back_compilation_files`, `test_committed_outcome_survives_staging_cleanup_failure` |
| MOD-COMP-06 | `test_preview_rejects_prohibited_output_paths`, `test_preview_rejects_source_and_control_path_overlaps` |
| MOD-COMP-07 | `test_discard_is_idempotent_and_surfaces_incomplete_cleanup` |
| MOD-COMP-08 | `test_apply_writes_exact_stage_and_private_audit` |

Additional suites characterize identity round-trips, plan protocol validation/migration, browser DTO behavior, capability declarations and imported-spec tracking. They do not establish complete browser/native conformance, editor acceptance or live integration behavior.

| Review | Outcome / remaining obligation |
|---|---|
| Whole-product Level 0 | Intake recorded for inspected shipped surfaces; validate at inventory. Production topology outside this checkout has not been confirmed. |
| Whole-product Level 1 | Open: complete dependency/ownership/interface mapping, classify data, trace remaining integration/state boundaries. |
| Compilation Levels 1â€“2 | Bounded observed contract and passing characterization captured; validate at verification with one category waiver. This is partial adoption, not whole-product conformance. |
| Compilation coverage waiver | `compilation-category-gap` covers only this slice's missing performance/scalability/observability categories; expires after verification and blocks release. MOD-COMP-09 owns follow-up. |
| Compilation residual gaps | MOD-COMP-10 symlink coverage; nested types, formal applicability and exceptional side-effect review remain open. |
| Release / Level 3 | Not accepted. No full local product gate, browser/WebGPU manual run, external formal model run or live integration execution was performed. |

Prepared/reviewed by Codex from source and local test output; maintainers own acceptance and remediation scheduling. A schema/metadata pass is supporting evidence only. Formal review is applicable to transaction locking/freshness/rollback; existing tests are not a proof and no product formal evidence is asserted.

## Validation and bounded work

Packaging of system-spec is still a proposal. Use the pinned sibling checkout for now; commands below assume the two repositories are siblings and run from `system-specification/reference-implementation/`:

```powershell
.\.venv\Scripts\python.exe metamodel.py ../../modelable/docs/superpowers/specs/system-spec/inventory.yaml --stage inventory
.\.venv\Scripts\python.exe metamodel.py ../../modelable/docs/superpowers/specs/system-spec/compilation.yaml --stage verification
.\.venv\Scripts\python.exe metamodel.py ../../modelable/docs/superpowers/specs/system-spec/compilation.yaml --context compilation-unit
.\.venv\Scripts\python.exe metamodel.py ../../modelable/docs/superpowers/specs/system-spec/compilation.yaml --impact apply-compilation
```

- Before validation, check the metamodel revision/schema hash against `baseline.json`; the vendored schema supports editor authoring, not semantic invariant execution.
- Before changing a contract, retain a baseline, run impact/context, trace nested dependencies, and use `--compat` after the edit. Matching prose sets cannot prove semantic compatibility.
- Record rerun source/dependency/environment revisions; invalidate affected evidence instead of reusing this run after code changes.
- Native format/lint/type/test/browser gates from [AGENTS.md](../../../../AGENTS.md) remain mandatory before commits/pushes. This docs-only onboarding does not change those gates.
- Suggested next handoff: finish compilation's transitive data/side-effect map and run the two symlink cases on a suitable host, then expand to registry/lock protocols and browser persistence.

## Feedback to system-spec

Suggestions and reproductions are recorded in the sibling system-specification repository at `feedback/modelable-onboarding.md` against the same pinned baseline:

1. Add explicit scope/adoption and external-boundary records rather than implying inventory means full product acceptance.
2. Separate existing authority/catalog imports from system-spec intake; document that `modelable spec` is a different command family.
3. Support unknown/provisional classifications without implicitly declaring data public.
4. Separate subject version from source revision in evidence validation.
5. Represent multi-phase local operations and committed-with-cleanup-error outcomes.
6. Model schema/dependency/evidence file bindings and skipped tests; retain native gates.
