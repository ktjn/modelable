# Modelable system-spec onboarding

- Historical intake: 2026-10-31. Product baseline: `0fead2321bdef11c72b2746eb57f3a8b0e327c94` (Modelable 1.15.1).
- Historical metamodel: system-specification `00188b037797fd37240dab9a0a11c431815e3ac9`; original schema retained as [schema-baseline.json](schema-baseline.json), original hashes/environment in [baseline.json](baseline.json). The manifest describes the original files at Modelable commit `5f48ed00`, not the migrated compilation/schema files.
- Compilation characterization: Modelable `72de182a47e1c045f586be73a2c3a79b68f9130b` (1.15.2), capture validator `b187e43628c7dc89935d17c2c382094ad37eb2eb`. Current [schema.json](schema.json), pins/hashes in [adoption.json](adoption.json), and [current recovery checks](evidence/recovery-validation.json). Prior captures remain historical.
- Status: whole-product inventory recorded; compilation behavior pinned for the bounded scope below, with explicit source/version and artifact bindings. Whole-product Levels 1–3 remain open.
- Live onboarding TODO: inventory and bounded compilation discovery recorded; [dependency/state map](compilation-map.md) covers 141 source modules and 19 declared dataclass shapes. The two missing symlink cases now pass on Linux. Shared IR/schema semantics, public failure catalog and remaining recovery/transport coverage, classification, quality criteria, formal assessment and release review remain open.
- This is internal development metadata. Product authority remains [architecture.md](../../../architecture.md), the existing capability catalog and native acceptance gates. The metadata changes no language, dependencies, installed skills or product commands. The accompanying native-gate repair moves graph controls above the canvas and makes browser characterization wait for the requested layout.
- `modelable spec` tracks dbt/FHIR/ODCS imports; use system-specification's validator for these files.

## Inventory and discovery

[inventory.yaml](inventory.yaml) registers shipped surfaces and coarse logical dependencies. Draft capabilities and omitted detailed data contracts are deliberate inventory gaps, not verified architecture.

| Surface | Observed entrypoint / source | Persistence and dependencies |
|---|---|---|
| Semantic toolchain | `cli/src/modelable/{compiler,parser,validation,planner,emitters,registry,operations}` | Local workspaces, plans, generated artifacts, registry SQLite, allocation ledgers, optional snapshots; these remain together at coarse inventory granularity. |
| Native CLI | `cli/pyproject.toml` → `modelable.cli:cli`; `bin/modelable*` launchers | Registers compiler, query, registry, dependency, import, integration and optional LLM workflows. Review command-specific side effects before extraction. |
| Language server | `commands/lsp.py` → `lsp/server.py`; stdio | Shared language/semantic engine and native conversation service; in-memory per-workspace indexes and debounced diagnostics. |
| Browser facade | `browser/api.py`, `browser/dispatch.py`, `cli/browser/pyproject.toml` | Same Python semantics through browser DTO/protocol adapters; browser wheel supports Python >=3.14,<3.15. Native package supports >=3.14. |
| Playground | `web/src/main.tsx`, `compiler.worker.ts`, `web/package.json` | Pyodide worker, IndexedDB workspace, service-worker assets; WebLLM/Ollama optional. Source, derived results and AI metadata have different lifetimes. |
| VS Code | `vscode/extension.js`, `vscode/package.json` | Launches configured Python/LSP process; explicit conversation preview/apply boundary. |
| Build/release/docs jobs | `.github/workflows/{validate,docs,release-prep,release-tag,release,codeql}.yml` | Development/delivery units, not deployed product services. Existing gates stay authoritative. |

- External-source names in YAML are categories observed in implementation/integration docs, not configured production endpoints. No live provider, registry, catalog or remote publication was exercised.
- Streaming runtime/materializer are deferred product concepts per architecture §§7/18, not invented deployable services. No shipped MCP server was found in this checkout.
- `tools/agentbuild` has local environment/cache remnants but no tracked files at this revision. The local-only `.agentbuild/` scratch exclusion is user-approved; scratch and native-gate logs stay outside product metadata.
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
- Modeled capability/data versions `1.0` identify this observed contract description, not separately published product APIs. Evidence pairs `subject_version: "1.0"` with the actual source commit, matched by `subject_bindings`. Source hashes cover the three operation files; transitive dependencies remain an open mapping obligation.

## Characterization and gate record

Current run: **238 passed, 2 skipped, zero reruns**, CPython 3.14.5 / pytest 9.1.1 / Windows at `72de182a`. [Output](evidence/recovery-characterization.txt), [command/environment/source pins](evidence/recovery-environment.json), [manifest](adoption.json). Fresh Linux symlink/cleanup follow-up: **4 passed, 0 skipped**. [Current review](compilation-recovery.md).

Earlier 221/2 and 295/6 captures retain their original source and limits. The [prior specification](evidence/compilation-before-recovery.yaml), [manifest](evidence/adoption-before-recovery.json), [Windows output](evidence/characterization-current.txt) and [environment](evidence/characterization-environment.json) are historical; they are not evidence for the changed implementation.

Run from `cli/` with a fresh, unused temp directory (do not point pytest at an existing valuable directory):

```powershell
$onboardingTemp = Join-Path (Get-Location) ('.venv/system-spec-pytest-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest tests/test_compilation_service.py tests/test_identity.py tests/test_plan_protocol.py tests/test_browser_api.py tests/test_capabilities.py tests/test_spec_tracking.py tests/test_compilation_cleanup_outcome.py tests/test_lsp_compilation_recovery.py tests/test_cli_compilation_errors.py tests/test_lsp_conversation_integration.py -n 0 -q -r s --tb=short --basetemp=$onboardingTemp -p no:cacheprovider
```

The two current Windows skips are the changed-resolved-parent and escaping-directory-symlink cases; directory symlink creation was unavailable. Both ran against the new pinned source on Linux alongside the two staging-cleanup regressions: **4 passed, 0 skipped**. Only the named symlink cases establish MOD-COMP-10. The new active Linux record supersedes the original failed Windows record; earlier Linux passes are retained as historical, not used with new source bindings. [Environment](evidence/recovery-linux-environment.json), [JUnit](evidence/recovery-linux.xml), and [recovery review](compilation-recovery.md) retain the limits. Windows privileges and universal filesystem conformance remain unproven.

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
| Compilation Levels 1–2 | Bounded observed contract and passing characterization captured; validate at verification with one category waiver. This is partial adoption, not whole-product conformance. |
| Compilation coverage waiver | `compilation-category-gap` covers only this slice's missing performance/scalability/observability categories; expires after verification and blocks release. MOD-COMP-09 owns follow-up. |
| Compilation dependency review | Bounded nested-record/import/state map recorded. Public error/adapter translation and crash/compensation review remain rework under MOD-COMP-09; shared IR/schema semantics and formal applicability are open. |
| Release / Level 3 | Not accepted. The onboarding PR #891 passed the full native gate, including browser and live integration checks. Current delivery results belong in the delivery PR; those gates do not close missing slice categories, skipped cases, formal applicability or browser/WebGPU manual acceptance. |

Prepared/reviewed by Codex from source and local test output; maintainers own acceptance and remediation scheduling. A schema/metadata pass is supporting evidence only. Formal review is applicable to transaction locking/freshness/rollback; existing tests are not a proof and no product formal evidence is asserted.

## Validation and bounded work

Published toolkit onboarding: [toolkit-upgrade-0.4.0.md](toolkit-upgrade-0.4.0.md). Use PyPI `system-spec-ref==0.4.0`; its intact offline export is committed at [tools/system-spec](../../../../tools/system-spec/WIRING.md). Follow the exported constitution plus the brownfield track. Existing project specification paths remain authoritative; no duplicate idealized baseline is created.

Run from the Modelable repository root:

```powershell
uv tool install --index-url https://pypi.org/simple system-spec-ref==0.4.0
system-spec --version
system-spec docs/superpowers/specs/system-spec/inventory.yaml --stage inventory --check-artifacts --root .
system-spec docs/superpowers/specs/system-spec/compilation.yaml --stage verification --check-artifacts --root .
system-spec docs/superpowers/specs/system-spec/compilation-contract-proposal.yaml --stage architecture --check-artifacts --root .
system-spec docs/superpowers/specs/system-spec/compilation.yaml --context compilation-unit
system-spec docs/superpowers/specs/system-spec/compilation.yaml --impact apply-compilation
system-spec docs/superpowers/specs/system-spec/inventory.yaml --plan local-contract-toolchain
system-spec docs/superpowers/specs/system-spec/inventory.yaml --diagram
```

The inventory `--diagram` output is embedded verbatim in the root README. Regenerate it with the command above when the intake changes. Keep the source path and reproduction command in this internal guide: the public-doc release check forbids `docs/superpowers` references in the root README. Captured versions and draft status remain inventory metadata, not current-release acceptance.

Offline fallback (Pydantic/PyYAML are already native CLI dependencies):

```powershell
uv run --project cli python tools/system-spec/reference-implementation/metamodel.py docs/superpowers/specs/system-spec/compilation.yaml --stage verification --check-artifacts --root .
```

- [toolkit-pypi-0.4.0.json](evidence/toolkit-pypi-0.4.0.json) records the published wheel, verified installation/export bytes and current schema/validator hashes. [packaged-toolkit-validation-0.4.0.json](evidence/packaged-toolkit-validation-0.4.0.json) records installed/offline parity and remaining acceptance blockers.
- [adoption.json](adoption.json) separates original capture/verifier pins from the current toolkit. Prior specification, schema and manifest are preserved in its `current_toolkit` record. Contracts/source bindings and verification state are unchanged; added test paths, explicit criterion mappings and environment fields are reviewed metadata, not reruns. The Linux test-file provenance correction retains its original execution artifacts and hashes.
- Toolkit version 0.4.0 is separate from modeled contract versions. The proposal still has three expected `COMPAT-04` diagnostics; compilation release and whole-product conformance remain open.
- Paths in source/provenance/artifact maps remain repository-relative. Review source/dependency/environment changes before reusing evidence; native semantic/manual gates remain authoritative.
- Upgrade using a pinned package version and a fresh destination, for example `system-spec export tools/system-spec-next` (it must not exist). Compare snapshots and their provenance, follow [WIRING.md](../../../../tools/system-spec/WIRING.md), revalidate active specs at their stages, and retain historical captures/decisions.

### Feature handoffs and scope

Follow [FEATURE.md](../../../../tools/system-spec/FEATURE.md) for changes to the existing specification. Run stage/artifact validation separately from diagnostic commands. The current compilation unit remains one consistency boundary, with assembly tests declared as `test_scope: integration`; unmodeled transitive providers remain discovery work.

```powershell
git diff --name-only origin/main | system-spec docs/superpowers/specs/system-spec/compilation.yaml --check-scope compilation-unit --changed -
system-spec docs/superpowers/specs/system-spec/compilation.yaml --check-return docs/superpowers/specs/system-spec/handoff-return-template.yaml
system-spec docs/superpowers/specs/system-spec/inventory.yaml --export backstage
system-spec docs/superpowers/specs/system-spec/inventory.yaml --export structurizr
```

- The scope command rejects unrelated paths. For a reviewed task, pass each shared file explicitly using repeatable `--allow <path>`; keep its exact allowlist in the handoff. Toolkit maintenance is outside the compilation unit, so its documentation/vendor paths must be reviewed separately rather than declared product ownership.
- Copy the [return template](handoff-return-template.yaml) to a task-specific file. Replace its unmet entries with current results where verified, retain unmet reasons and findings, and list actual changed paths. Its current all-unmet state passes structural checking; this is not an accepted handoff. System-scoped MOD-COMP-09 and native/manual/release gates require separate review.
- Split specs, external/imported providers, domains, mediation and fakes are available in the imported toolkit. This migration does not assert previously undiscovered topology or isolated tests. Keep coherent boundaries and bind new fields only after discovery.
- Backstage's default owner is `unknown`; exports are review inputs, not registered services. Neither export implies a deployed service topology or changes the captured draft status.

### Historical evidence migration decision

| Check / precise scope | Observation / decision |
|---|---|
| Historical preservation | Original baseline, run and metadata validation remain unchanged; original schema retained separately. Git commit `5f48ed00` preserves the original specification. |
| Historical migration characterization | 221 passed, 2 skipped on the original 1.15.2 source; unchanged files at that capture. The later cleanup repair and source-bound refresh are recorded separately below. |
| Metadata / local integrity | Inventory and compilation verification pass with `--check-artifacts --root .`; the existing category waiver remains. Top-level DTO field-name sets match source. |
| Contract compatibility | Capability/data compatibility against the original compilation specification passes; no contract clauses or data fields changed. |
| Evidence binding | Eight passing records match contract `1.0` and current source bindings. Release diagnostics contain no EV-04 mismatch. Five negative probes reject stale revisions/versions, missing bindings, and mismatched source/log hashes. |
| Historical skipped evidence | At this migration capture, MOD-COMP-10 was unverified and its skipped record blocked release. The later suitable-host rerun supersedes that partial record; historical output is retained. |
| Acceptance | Evidence-format migration verified within this slice. Maintainers own final acceptance; whole-product Levels 1–3 and compilation release remain open. |

Detailed results and remaining release diagnostics: [migration-validation.json](evidence/migration-validation.json). Validation cannot prove Git authenticity, full dependency correspondence or criterion coverage. The existing restricted handling policy remains provisional; this migration does not close classification review. Current follow-up: the bounded [compilation map](compilation-map.md) and suitable-host symlink evidence are recorded. Next reconcile public helper/adapter error boundaries and lock/compensation obligations, then expand shared registry protocols and browser persistence. The original migration manifest is retained as [adoption-before-dependency-map.json](evidence/adoption-before-dependency-map.json). Prior dependency validation: [dependency-validation.json](evidence/dependency-validation.json). Current source-bound recovery validation: [recovery-validation.json](evidence/recovery-validation.json).

## Feedback to system-spec

Suggestions and reproductions are recorded in the sibling system-specification repository at [`archive/feedback/modelable-onboarding.md`](https://github.com/ktjn/system-specification/blob/main/archive/feedback/modelable-onboarding.md). Findings 1–6 describe the original baseline; system-specification PR #30 implemented their supporting process/model changes:

1. Add explicit scope/adoption and external-boundary records rather than implying inventory means full product acceptance.
2. Separate existing authority/catalog imports from system-spec intake; document that `modelable spec` is a different command family.
3. Support unknown/provisional classifications without implicitly declaring data public.
4. Separate subject version from source revision in evidence validation.
5. Represent multi-phase local operations and committed-with-cleanup-error outcomes.
6. Model schema/dependency/evidence file bindings and skipped tests; retain native gates.

Migration feedback: use one repository-relative provenance file plus an optional selector, bind additional artifacts separately, and retain historical validator decisions when upgrading. Optional artifact checks validate bytes and paths; they do not validate command selectors, dependencies or whole-product acceptance.

Native-gate repair: delivery exposed a pre-existing dense-graph/control overlap that the old test could miss by sampling the previous mode. The repair separates controls from the canvas and retains the original zoom/no-overlap assertions, with explicit layout readiness and zoom/fit interaction checks. Compilation source/test pins remain unchanged; the UI repair is outside that Python slice. Final exact-commit native-gate results are recorded in the PR.

Dependency discovery preserves the five modeled top-level DTOs and current contract versions. Static imports do not imply runtime calls or deployed providers: OCI is unsupported, `AffectedDefinition` is a shared editor-module record, and `protoc` is a separate local tool boundary. Git exports for Linux capture explicitly disable autocrlf and select LF; exported implementation/test bytes are checked against Git blobs before execution. The completed [migration plan](../../plans/archived/system-spec-evidence-migration.md) is archived; the onboarding specification remains active.

Error-boundary follow-up: [completed error review](../archived/system-spec-compilation-errors.md) records the Python/CLI/conversation/LSP/VS Code outcome matrix and the CLI operational-error repair. [Source-bound characterization](evidence/error-boundary-characterization.json) captures the immutable code commit, six new CLI cases and 295 passing focused tests with six platform skips. The frozen failure catalog remains rework under MOD-COMP-09; adding discovered modes is not silently treated as compatible. The completed [dependency-map plan](../../plans/archived/system-spec-compilation-dependencies.md) is archived after PR #894 merged.

Current follow-up: [compilation-recovery.md](compilation-recovery.md) records the successful-promotion staging-cleanup repair and actual stdio fault/retry matrix. Active source bindings/evidence are refreshed at `72de182a`; the previous passing records/specification/manifest remain historical. `EV-02` failed-evidence supersession is used only for the original skipped symlink record. The completed [CLI-error plan](../../plans/archived/system-spec-compilation-errors.md) is archived after PR #895 merged. Public failure-catalog correction and broader MOD-COMP-09 obligations remain open.


## Proposed failure-catalog correction

[compilation-contract-review.md](compilation-contract-review.md) records operation-specific observed failures, consumer gaps and the next acceptance handoff. [The proposal](compilation-contract-proposal.yaml) describes direct/preview/apply at modeled 2.0 and discard at 1.0; active `compilation.yaml` remains 1.0 with unchanged passing evidence. Candidate architecture metadata and 35 passing as-is tests do not approve activation or remediate the documented CLI/editor gaps. Incompatibility diagnostics remain visible.

The merged [recovery implementation plan](../../plans/archived/system-spec-compilation-recovery.md) is archived after PR #896. Its source-bound recovery review and current adoption manifest remain active because their broader contract/recovery acceptance obligations and artifact references are still open.

## CLI consumer remediation

[CLI dependency-error remediation](cli-dependency-errors.md) records the narrow JSON/SQLite operational-error presentation repair at `41e4716c`, six new desired-behavior cases and a 41-test source-bound capture. Historical defect output and core service bindings remain intact. The corrected-contract proposal stays unaccepted; preview/LSP/editor recovery and external consumer disposition remain open.

## Conversation preview recovery

[Preview recovery](preview-recovery.md) records operational-error replies, retained action metadata, real protocol negotiation and artifact-reference navigation at `2146fed9`: 168 Python/RPC passes (one existing platform skip) and 37 native editor passes. Manual/model acceptance, other fault families, external consumers and contract activation remain open.
