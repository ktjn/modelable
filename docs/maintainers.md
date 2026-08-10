# Maintainer and Agent Guide

This document defines how automated and human-assisted agents operate within the
[Project Governance](https://github.com/ktjn/modelable/blob/main/GOVERNANCE.md).
It is process guidance for agents, not product semantics. The product source of
truth remains
[architecture.md](architecture.md).

## 1. Purpose

Agent governance exists to keep repository changes reviewable, locally
verifiable, and aligned with Modelable's core contract guarantees and
[Product Principles](https://github.com/ktjn/modelable/blob/main/GOVERNANCE.md#3-product-principles-in-governance):

- Published model and projection versions are immutable.
- Incompatible changes require new versions.
- Lineage, compatibility, governance findings, and generated artifacts must be deterministic.
- Adapter-specific details must not leak into platform-neutral model and projection definitions.
- PII, restricted fields, and unauthorized fields must not be exposed through projections, generated artifacts, logs, or dead-letter payloads.

These rules apply to documentation, samples, future source code, tests, generated artifacts, CI configuration, and PR preparation.

## 2. Agent Operating Rules

Agents must:

- Consult [AGENTS.md](https://github.com/ktjn/modelable/blob/main/AGENTS.md)
  for the current project state and
  [ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) for
  planned work before starting.
- Read the relevant specification before editing.
- Keep changes small enough for meaningful review.
- Add or update tests with any code change that affects parser behavior, validation, compatibility checks, lineage, planning, runtime execution, governance, security, or generated artifacts.
- Prefer behavior and contract tests over implementation-shape tests. A test
  should normally exercise the public command, exported function, generated
  artifact, policy contract, or workflow behavior. Avoid assertions that only
  prove a private helper, literal string, control-flow shape, or file layout is
  present unless that detail is itself the reviewed contract.
- Add Docker-backed compile smoke tests for any change that adds or modifies a generated-language backend or generated artifact format, using the latest official compiler/runtime image for each affected language.
- Run the OpenMetadata Testcontainers smoke for any change that can affect the
  OpenMetadata export format, including `openmetadata` emitter code, shared
  emitter metadata helpers, IR field/governance metadata shape, projection
  lineage resolution, or OpenMetadata CLI/documentation contracts.
- Run the Marquez/OpenLineage Testcontainers smoke for any change that can
  affect OpenLineage event export or live lineage synchronization, including
  `openlineage` emitter code, the OpenLineage registry client, sync command
  wiring, shared emitter metadata helpers, projection lineage resolution, or
  OpenLineage CLI/documentation contracts.
- Run the Data Contract CLI lint smoke for any change that can affect the ODCS
  export format, including `odcs` emitter code, shared emitter metadata helpers,
  IR field/governance metadata shape, or ODCS CLI/documentation contracts.
- Run the HL7 FHIR Validator smoke for any change that can affect the FHIR R4
  profile export format, including `fhir-profile` emitter code, shared emitter
  metadata helpers, IR field/governance metadata shape, or FHIR CLI/documentation
  contracts.
- Do not use hard-coded line numbers to locate language elements in test fixtures or sample files. Derive line positions dynamically.
- Validate current latest stable framework, library, CLI, build-tool, and scaffolding choices with a web search against official documentation, package registries, or release pages before adding or changing them.
- Use the latest stable framework and tool versions by default, unless the specification, compatibility constraints, existing manifests, or explicit user direction require a different version.
- Record any deliberate use of an older framework or tool version in the final handoff or PR body.
- Use `uv` exclusively for Python version management, project setup, dependency management, lockfile generation, and tool execution. Keep packages up to date with the latest stable versions.
- The project requires Python >= 3.14 (declared in `cli/pyproject.toml` `requires-python` and `[tool.mypy] python_version`). All agents and CI must run under Python 3.14+ for Pydantic v2 validation and modern typing behavior. Strict mypy is enforced as a CI baseline ratchet: existing errors are tracked in `cli/mypy-baseline.txt`, new errors fail the Validate workflow, and resolved baseline lines should be removed as modules are cleaned up.
- Preserve the existing domain language: domain-owned canonical models, immutable versions, projections, subscriptions, adapter bindings, planner/runtime/materializer, compatibility, lineage, and governance.
- Maintain backward compatibility within major versions for the `.mdl` language and CLI.
- Prefer explicit derivation and traceability over implicit behavior.
- Identify whether a change is MVP, deferred, non-goal, or open decision when adding requirements.
- Avoid broad architecture or tooling churn unless it directly supports the requested change.
- Record verification evidence in the final handoff or PR body.
- **Local CI Requirement**: Run the full local gate and ensure all tests pass before reporting a task as complete or creating a PR.
- **GitHub Verification**: Verify that GitHub Actions CI passes for any pushed changes.
- **Strategic Re-evaluation**: If a fix fails more than 3 times, stop and re-evaluate assumptions. Propose an alternative architectural approach rather than continuing to patch a failing one.

Agents must not:

- Weaken published-contract semantics.
- Reclassify governance findings as non-blocking implementation details without documenting the policy decision.
- Collapse registry, compiler/planner, runtime, materializer, and adapter boundaries for convenience.
- Commit transient local artifacts such as dependency folders, build outputs, caches, test result directories, local environment files, or fetched Helm dependencies.

## 3. Local Gate

Every completed change must pass a local gate before it is reported as complete.

Minimum local gate:

```text
git status --short
review changed-file diff
run relevant tests or checks
report commands run and skipped checks
```

Documentation-only local gate:

```text
git status --short
review Markdown diff
confirm links and document references are coherent
confirm terminology matches the system specification
```

CLI implementation local gate:

```text
git status --short
uv sync --extra dev
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ -v
uv run modelable validate tests/fixtures/customer.mdl
```

Run these commands from `cli/`. The final non-mutating Ruff checks are required
after any auto-fix or formatting step; they mirror the first CLI gates in
GitHub Actions and prevent unformatted changes from skipping the test suite.
If the formatter or static-analysis commands change, update this section,
[AGENTS.md](https://github.com/ktjn/modelable/blob/main/AGENTS.md), and
[CONTRIBUTING.md](https://github.com/ktjn/modelable/blob/main/CONTRIBUTING.md)
together.
**If a milestone is completed, update the status table in
[AGENTS.md](https://github.com/ktjn/modelable/blob/main/AGENTS.md).**

For LSP or VS Code extension changes, also run:

```text
cd vscode
npm ci
npm run build
npm test
```

For changes to the `.mdl` grammar or language documentation, regenerate the
derived artifacts and confirm their drift tests pass. The Lark grammar at
`cli/src/modelable/grammar/modelable.lark` is the single source of truth for
the language:

- `docs/grammar.md` is rendered by `cli/scripts/render_language_grammar.py`
  (`cli/tests/test_grammar_doc_sync.py` enforces it is up to date).
- The TextMate keyword/type lists in
  `vscode/syntaxes/modelable.tmLanguage.json` and the Monarch lists in
  `web/src/language/monaco-providers.ts` are rendered by
  `cli/scripts/render_editor_grammars.py`
  (`cli/tests/test_editor_grammar_sync.py` enforces they are up to date).

Regenerate after grammar edits with:

```text
cd cli
uv run python scripts/render_language_grammar.py
uv run python scripts/render_editor_grammars.py
```

A grammar change that adds a keyword or type word shows up in the editor
grammars automatically; a parser change that only rewrites existing rules
should leave the editor lists unchanged.

On Windows, close any running desktop VS Code windows before `npm test`; the smoke runner fails fast if the desktop app is still holding the update mutex.

For conversational compilation changes, exercise both application-service
callers. Direct `modelable compile` must preserve its public targets, options,
console behavior, output bytes, and errors. A chat acceptance case must use a
fake provider to preview `compile this workspace to Rust`, confirm that no
workspace bytes changed, capture the exact staged bytes and affected
definitions, then issue the literal `/apply` and compare every written byte to
staging. Also verify that:

- changing a source, generated destination, registry input, parent path, or
  staged file makes apply stale;
- dirty generated destinations block VS Code apply while unrelated dirty files
  do not;
- an injected promotion or audit failure restores prior files and removes new
  transaction paths;
- discard, replacement, expiry, reset, quit, and exceptional close remove
  private staging; and
- `.modelable/audit/compilations/<action-id>.json` contains hashes, sizes,
  canonical plan, affected references, and confirmation provenance, but no
  prompt, response, source/artifact content, credentials, tokens, environment
  values, or unrelated paths.

Keep conversational planning local-only. CLI, VS Code, and the playground use
the same typed Python conversation engine with filesystem and in-memory
adapters. Browser tests use the semantic simulator; real-model checks are
opt-in:

```text
cd cli
$env:MODELABLE_OLLAMA_TESTS='1'
$env:MODELABLE_OLLAMA_MODEL='qwen2.5-coder:14b'
uv run pytest tests/test_ollama_conversation_conformance.py -v -n 0
```

The suite uses `MODELABLE_LLM_BASE_URL` or `http://127.0.0.1:11434`, never
downloads models, and does not make Ollama a playground provider. Registry
synchronization, publishing, and external actions remain outside the
conversation plan vocabulary. Preview text over 2 MiB must continue to fail
with guidance to use direct `modelable compile`.

For release pipeline or packaging metadata changes, also run:

```text
cd cli
uv run pytest tests/test_release_metadata.py tests/test_release_workflow.py -v
```

For browser compiler or playground changes, run the complete playground gate and
compose the same combined Pages artifact used by CI from the repository root:

```powershell
uv run python .github/scripts/run_browser_playground.py
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
uv run --project cli python .github/scripts/assemble_pages.py --site site --web-dist web/dist
```

Pull requests only build and test the browser playground. Only pushes to `main`
deploy the combined documentation and playground artifact.

### Manual real-model WebLLM chat conformance

`tests/ai-actions.spec.ts` exercises the assistant panel against the
deterministic `?ai=simulator` provider and always runs in CI. Real-model
checks against WebLLM/WebGPU are opt-in, like the CLI's Ollama conformance
suite above, and never run automatically:

```text
cd web
npm run build
npm run test:e2e:manual
```

This drives every model in the curated allowlist
(`web/src/ai/curated-models.ts`, the same list `ai.worker.ts` filters the
WebLLM catalog down to) through every chat use case, per model:

- create an entity from scratch and accept it;
- apply a natural-language update to an existing entity and confirm prior
  fields survive alongside the new one (not a wholesale replacement);
- suggest a projection for an existing entity, accept it, and confirm a real
  `projection` definition was written, not just an explanation;
- explain the workspace; and
- generate an entity and discard it, confirming the source is untouched.

The update and projection steps also assert the workspace has zero
diagnostics after the AI-applied change, i.e. the generated `.mdl` actually
validates, not just that the chat turn avoided an `AI_ERROR`. Restrict to a
subset for a faster loop:

```text
MODELABLE_WEBLLM_TEST_MODELS=Qwen2.5-0.5B-Instruct-q4f16_1-MLC npm run test:e2e:manual
```

**Run this suite whenever you touch what it exercises** — it is opt-in
precisely because it needs real WebGPU hardware and bandwidth, not because
it is optional to keep passing. That includes changes to:

- `web/src/ai/**` (provider, worker, curated model list, `ChatPanel.tsx`);
- `App.tsx`'s conversation wiring (`runConversation`, `handleAiAccept`,
  `handleAiDownload`, `handleAiFetchModels`);
- the shared Python conversation engine or plan schema
  (`cli/src/modelable/llm/conversation_engine.py`,
  `conversation_planner.py`, `conversation_plan.py`,
  `cli/browser/conversation.py`) — these decide what a chat turn is allowed
  to change and how updates/projections get validated before preview; or
- the `@mlc-ai/web-llm` dependency version.

A model-download-only change (e.g. adding a curated model id) only needs
that one model exercised via `MODELABLE_WEBLLM_TEST_MODELS`; changes to the
conversation engine or plan schema affect every provider and warrant the
full default run across all curated models.

It needs a real WebGPU adapter, so it runs headed by default (set
`PLAYWRIGHT_HEADLESS=1` only on a machine with confirmed working headless
WebGPU) and skips itself with a clear reason if no adapter is available.
Downloaded model weights persist in a browser profile under
`web/output/webllm-profile/` (gitignored) so repeat runs do not
re-download; delete that directory to force a clean fetch after bumping
`@mlc-ai/web-llm` or changing the curated model list.

### Browser playground troubleshooting

- **Bumping `searchable-analysis`/`searchable-client` (or any package listed
  in `cli/browser/browser-lock.json`'s `externalWheels`):** `cli/uv.lock` and
  `cli/browser/browser-lock.json` are two *separate* lockfiles. `uv lock`
  only updates the former, which the CLI and LSP read; the Playground builds
  its own browser wheel from the latter and ignores `uv.lock` entirely. A
  dependency fix that only updates `uv.lock` ships correctly to the CLI/LSP
  while the deployed Playground silently keeps running the old, unfixed
  version — no error, no failing test, nothing to notice until a user
  reports the old behavior (this exact thing happened once already; see
  `git log --oneline -- cli/browser/browser-lock.json`). After `uv lock`,
  update `browser-lock.json`'s `version`/`fileName`/`url`/`sha256` for that
  package to the matching published wheel (`https://pypi.org/pypi/<name>/<version>/json`
  lists the wheel's exact URL and `digests.sha256`), then run `npm run
  prepare:python` from `web/` to checksum-verify it. `cli/tests/test_repository_release.py::test_browser_lock_matches_uv_lock_searchable_versions`
  enforces that `searchable-analysis`/`searchable-client` stay in sync
  between the two lockfiles specifically; it does not cover other
  `externalWheels` entries (currently `lark`, `pyodide-http`).
- **Checksum or manifest failure during `prepare:python`:** do not patch
  generated files under `web/public/python`. Confirm
  `cli/browser/browser-lock.json` contains the intended pinned identities, then
  run `npm run prepare:python` from `web/`. The wheel builder writes its
  SHA-256 to `browser-manifest.json`. The vendor step validates its complete
  plan before mutation and preserves the generated Modelable wheel and browser
  manifest during cleanup. Each downloaded archive is checksum-verified before
  that archive is written. A checksum failure stops the build but may leave
  generated staging incomplete; correct the lock or source and rerun the build.
- **`INITIALIZATION_FAILED` or an unavailable editor:** inspect the browser
  console for Monaco worker startup failures and the network panel
  for the same-origin `pyodide/`, `python/runtime-manifest.json`, and two
  manifest wheel requests, then run `npm run build` and `npm run test:e2e` from
  `web/`. Monaco editor and JSON workers are bundled as same-origin assets, just
  like the pinned Pyodide runtime and Python wheels. The production UI
  deliberately sanitizes Python and worker exceptions, so use the development
  console and failed request status rather than expecting a traceback in the
  page.
- **Native/browser conformance mismatch:** run
  `uv run python .github/scripts/run_browser_playground.py`. Review the fixture and
  normalized result difference before changing snapshots. Regenerate
  `cli/tests/conformance/browser/snapshots` with
  `uv run --project cli python cli/scripts/write_browser_conformance.py
  --output cli/tests/conformance/browser/snapshots` only for an intentional,
  reviewed semantic change.
- **Size or timing budget failure:** run `npm run build`, then
  `npm run check:budgets` and `npm run test:e2e` from `web/`. The JSON output
  identifies the wheel, application, additional-Python, and Monaco size
  categories. Monaco is reported separately without a limit; the existing
  compiler application, wheel, Python dependency, and timing budgets remain
  enforced. Playwright prints initialization, validation, and generation
  medians. Keep the enforced budgets fixed unless an approved design change
  explicitly revises them.
- **GitHub Pages base-path failure:** keep Vite's base at
  `/modelable/playground/`, build both surfaces, and run
  `uv run --project cli python .github/scripts/assemble_pages.py --site site
  --web-dist web/dist` from the repository root. Confirm
  `site/playground/index.html` exists and generated HTML contains no
  origin-root `/assets/` URLs. The assembler must compose the proof into the
  MkDocs output; deploying `web/dist` by itself drops the documentation.

## 4. Test Gates

Test gates are selected by risk and touched surface.

| Touched surface | Required gate |
|---|---|
| Documentation only | Markdown diff review, link/reference coherence check, terminology check against the system spec |
| `.mdl` samples or fixtures | `uv run modelable validate <path>` from `cli/` when the touched file is expected to be supported by the current parser/compiler; otherwise manual grammar and semantic review with the unsupported construct stated in the handoff |
| Parser, IR, or semantic validation | Focused parser/validation tests plus the full local compiler gate |
| Planner, lineage, compatibility, or governance | Focused tests for changed behavior plus representative projection and governance fixtures |
| Emitters or generated artifacts | Focused emitter tests, deterministic output comparison, fixture regeneration review, and Docker-backed compile smoke tests for every affected language backend |
| OpenMetadata export format | `uv run pytest tests/test_emit_openmetadata.py -q` plus `MODELABLE_OPENMETADATA_TESTCONTAINERS=1 uv run pytest tests/test_openmetadata_testcontainers.py -q` from `cli/` |
| OpenLineage export or sync format | `uv run pytest tests/test_emit_openlineage.py tests/test_openlineage_sync.py -q` plus `MODELABLE_OPENLINEAGE_TESTCONTAINERS=1 uv run pytest tests/test_openlineage_testcontainers.py -q` from `cli/` |
| ODCS export format | `uv run pytest tests/test_emit_odcs.py -q` plus `MODELABLE_DATACONTRACT_CLI=1 uv run --with datacontract-cli pytest tests/test_emit_odcs.py --tb=short -q` from `cli/` |
| Protobuf export format | `uv run pytest tests/test_emit_protobuf.py tests/test_codegen_targets.py -q` from `cli/` |
| Scalable gRPC export format | `uv run pytest tests/test_emit_grpc.py tests/test_emit_protobuf.py tests/test_codegen_targets.py -q` from `cli/` |
| FHIR R4 profile export format | `uv run pytest tests/test_emit_fhir.py tests/test_fhir_validator.py -q` plus `MODELABLE_FHIR_VALIDATOR=1 MODELABLE_FHIR_VALIDATOR_JAR=<path-to-validator_cli.jar> uv run pytest tests/test_fhir_validator.py --tb=short -q` from `cli/` when the HL7 validator jar is available |
| LSP, VS Code extension, or editor integration | Focused LSP tests plus `cd vscode && npm ci && npm run check && npm run build && npm test && npm run package` |
| Conversational compilation | Focused conversation, compilation service, transaction, audit, protocol, and VS Code tests; fake-provider preview/apply acceptance; exact staged-byte and audit-privacy checks; then the complete CLI and VS Code gates |
| Browser compiler or playground | `uv run python .github/scripts/run_browser_playground.py` plus strict MkDocs build and combined Pages assembly |
| Release pipeline or packaging metadata | Focused release metadata/workflow tests plus the full local CLI gate |
| Runtime, subscriptions, adapters, or materializers | Unit tests, integration or smoke tests for the adapter boundary, and failure-mode coverage |
| Security, permissions, PII, or restricted fields | Negative tests proving unauthorized exposure is rejected or reported as a governance finding |

Compatibility, lineage, and governance tests must include negative cases when behavior can fail unsafely.

Workflow and policy tests should exercise reusable scripts or parse structured
workflow data where feasible. Avoid broad "contains this exact text" assertions
for CI behavior when the same requirement can be checked by running the routing
logic, parsing the workflow jobs, or inspecting generated outputs.

## 5. Pull Request Handling

PRs should be narrow and explicit.

Every PR should include:

- Intent: what product or repository behavior changes.
- Scope: documents, modules, samples, or generated artifacts touched.
- Verification: exact local commands or checks run.
- Risk: compatibility, lineage, governance, PII, generated artifact, or runtime risks.
- Deferred work: any intentionally skipped follow-up.

PRs that change published contract semantics, compatibility rules, governance findings, lineage resolution, access policy, or generated artifacts should remain draft until the local gate passes and the relevant risks are documented.

Review feedback is blocking when it identifies:

- A possible weakening of immutable published-contract semantics.
- Missing or incorrect lineage.
- Lowered, omitted, or incorrect classification metadata.
- PII or restricted-field exposure.
- Non-deterministic generated artifacts or registry output.
- Missing tests for compiler, planner, compatibility, lineage, governance, or security behavior.

## 6. CI and Remote Gate Expectations

Remote CI mirrors the local Ruff, test, VS Code, dependency-audit, and
external-smoke gates for the changed surface. It does not replace local
verification for ordinary development.

Recommended CI gate sequence as implementation expands:

```text
format check
mypy baseline ratchet
unit tests
dependency audit
fixture-based compiler tests
lineage, compatibility, and governance regression tests
emitter determinism tests
component smoke tests where applicable
```

CI failures must be investigated from the first failing gate. Agents should not rerun failed CI repeatedly without first reading the failure context.

The Validate workflow starts with a cheap changed-surface detector. Pull request
and push runs execute only the jobs relevant to the files changed in that run;
manual `workflow_dispatch` runs execute every validation job. Changes to the
Validate workflow or its workflow regression tests force every validation job so
CI edits are self-tested.

The CLI job runs strict mypy through
`.github/scripts/check_mypy_baseline.py`. The script compares current mypy
output with `cli/mypy-baseline.txt`: new error lines fail CI, while resolved
lines are reported so the baseline can shrink in the same PR that fixes them.

The OpenMetadata live-smoke CI job must run with
`MODELABLE_OPENMETADATA_TESTCONTAINERS=1` when changes affect the OpenMetadata
export format so the generated artifact is checked against a live OpenMetadata
server stack.

The OpenLineage live-smoke CI job must run with
`MODELABLE_OPENLINEAGE_TESTCONTAINERS=1` when changes affect OpenLineage export
or sync behavior so generated events are posted to a live Marquez-compatible
lineage backend.

The ODCS lint-smoke CI job must run with `MODELABLE_DATACONTRACT_CLI=1` and
`datacontract-cli` available when changes affect the ODCS export format so
generated ODCS artifacts are checked against the upstream validator.

The FHIR Validator CI job must run with
`MODELABLE_FHIR_VALIDATOR=1` and `MODELABLE_FHIR_VALIDATOR_JAR` pointing at the
HL7-maintained `validator_cli.jar` when changes affect the FHIR R4 profile
export format so representative generated R4 `StructureDefinition` profiles are
checked against the upstream validator.

Release changes must also verify package metadata, archive contents, clean-wheel
installation, version agreement, and the manual release dry run. Tag-triggered
publishing uses the protected `pypi` environment and trusted publishing; agents
must not add long-lived package-index credentials to repository secrets.

## 7. Open Decisions

- Whether governance findings become blocking CI failures is an open policy decision. Phase 1 treats them as visibility and process-support findings unless a policy wrapper promotes them to failures.
- The PR template location and required status checks are open until repository hosting configuration is added.

## 8. Release Process

Releases are built from version tags. The tag, Python package, VS Code extension,
changelog, wheel, sdist, VSIX, checksums, and release manifest must agree on the
version.

There are two ways to prepare a release: the automated one-click flow (preferred,
below) or the manual command sequence (further down). Both converge on the same
things — a focused release PR that bumps the version and freezes the changelog,
then pushing the `v<version>` tag, which triggers the publish workflow.

### Automated one-click release

`.github/workflows/release-prep.yml` and `.github/workflows/release-tag.yml`
automate the mechanical part of a release. From the GitHub Actions UI, run the
**Prepare release** workflow manually with a `version` input (e.g. `1.5.0`);

1. Visit **Actions → Prepare release → Run workflow**, set the `version`
   (e.g. `1.5.0`) and, if desired, enable `auto_merge`.
2. The workflow bumps `cli/pyproject.toml`, `cli/browser/pyproject.toml`,
   `vscode/package.json`, and the two top-level `version` fields of
   `vscode/package-lock.json`, moves the `## [Unreleased]` changelog entries
   into a dated `## [<version>] - <date>` section (leaving a fresh empty
   `Unreleased` section), and regenerates `cli/uv.lock`. It then opens a
   `Release <version>` PR.
3. Review the PR diff (especially `CHANGELOG.md` and the English of the entries)
   and merge it. If `auto_merge` was enabled, the PR merges itself once CI is
   green.
4. Once the release PR merges, `release-tag.yml` detects the merge, derives the
   version from the `Release <version>` title, and pushes the annotated
   `v<version>` tag. That tag triggers `.github/workflows/release.yml`, which
   re-verifies and publishes (see the tag behavior below).

Because the bump is scripted, the version input must be a clean `X.Y.Z` that is
not already tagged, and it should match the changelog's substance (minor = new
backward-compatible feature/flag, patch = fixes only — see
[§9](#9-1x-compatibility-policy)). Always inspect the generated PR: the script
is mechanical and does not judge the changelog content.

### Manual command sequence

1. Move user-facing changelog entries from `Unreleased` into a dated release.
2. Set the same version in `cli/pyproject.toml`, `cli/browser/pyproject.toml`,
   and `vscode/package.json`. `cli/browser/pyproject.toml` must match
   `cli/pyproject.toml` exactly — `build_browser_wheel.py` refuses to build a
   browser wheel when the two disagree.
3. Run the complete local gates in this document and `CONTRIBUTING.md`.
4. Run the release workflow manually; this validates artifacts without publishing.
5. Merge the focused release pull request.
6. Create and push an annotated version tag.
7. Verify PyPI, the GitHub release, checksums, manifest, and VSIX.
8. Install the published wheel in a clean environment and run
   `modelable --version` plus strict sample validation.

The concrete commands for the manual path are given [below](#concrete-command-sequence).

PyPI publishing uses trusted publishing through the protected `pypi`
environment. Do not add long-lived package-index credentials. Do not blindly
rerun a failed publication; inspect the first failure and publish a new version
if an immutable artifact already reached the index.

### Concrete command sequence (manual path)

Determine the version bump from the changelog-worthy commits since the last
tag (`git log v<last>..HEAD --oneline`): a new backward-compatible feature or
flag is a minor bump, a fix-only set of commits is a patch bump, per
[§9](#9-1x-compatibility-policy).

```text
git checkout main && git pull --ff-only
git checkout -b release-<version>

# Edit CHANGELOG.md: rename `## [Unreleased]` content into a new
# `## [<version>] - <date>` section (keep an empty `## [Unreleased]` above it).
# Bump the version in cli/pyproject.toml, cli/browser/pyproject.toml, and
# vscode/package.json to match.
cd cli && uv lock                       # regenerates cli/uv.lock's modelable entry
# vscode/package-lock.json needs the same version at its top two "version"
# fields only (root package + the "" entry) — do not touch dependency
# entries that happen to share the same version number.

uv run ruff format --check .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest tests/ -q --deselect tests/test_llm_provider_integration.py --deselect tests/test_codegen_docker_smoke.py

cd .. && git add CHANGELOG.md cli/pyproject.toml cli/browser/pyproject.toml cli/uv.lock vscode/package.json vscode/package-lock.json
git commit -m "Release <version>"
git push -u origin release-<version>
gh pr create --title "Release <version>" --body "..."
```

Before opening the release PR, confirm the full test suite is green on a
fresh checkout of `main` — `test_repository_release.py::test_local_markdown_links_resolve`
and the other repository-hygiene checks in that file are release gates but
are not path-gated the same way as CLI code changes, so an unrelated
docs/archival change on `main` can silently break the release pipeline
between releases. Fix any such break in its own PR before the version-bump
PR, so the release commit stays focused on the version bump.

After the release PR merges (manual path only — the automated flow tags for you):

```text
git checkout main && git pull --ff-only
git tag -a v<version> -m "Release <version>"
git push origin v<version>
```

Pushing the tag triggers `.github/workflows/release.yml`: it re-runs the full
gate, builds the wheel/sdist/VSIX, verifies a clean install, then (on the tag
push, not `workflow_dispatch`) publishes to PyPI via trusted publishing and
creates the GitHub release. Watch the workflow run to completion before
telling anyone the release shipped — a failure after the build job but before
`publish` means nothing reached PyPI even though the tag exists.

### 1.0 release outcome

Modelable 1.0 is tagged and published. The PyPI publish job uses trusted
publishing through the protected `pypi` environment, repository documentation
uses the 1.0 stable-surface language, and `SECURITY.md` defines the current
1.0.x support policy. The VS Code Marketplace publish job remains disabled
because Marketplace distribution is deferred from the 1.0 surface.

## 9. 1.x Compatibility Policy

Modelable follows semantic versioning within the stable surface defined in
`README.md` and `ROADMAP.md`.

**Additive changes (1.x minor releases):**

- New CLI flags, commands, or output fields that do not change existing
  behavior when not used.
- New generated artifact formats or new emitter options.
- New `.mdl` syntax that is backward-compatible with existing files.
- New diagnostic codes (new errors do not break files that previously passed,
  unless the file was relying on a missing check).

**Breaking changes require a major version bump:**

- Removing or renaming a CLI command, flag, or stable output field.
- Changing the shape of a generated artifact in a way that breaks existing
  consumers (e.g., renaming a Rust struct field, changing a TypeScript import
  path).
- Changing `.mdl` parsing rules that cause previously valid files to fail
  validation.
- Changing compatibility, lineage, or governance report output in a way that
  silently changes findings for existing models.

**Not covered by the stable surface (may change in 1.x):**

- Internal IR types, resolver internals, and private module APIs.
- Language server protocol message shapes (LSP compatibility is maintained
  with VS Code, not with direct LSP clients).
- Experimental or beta-labeled commands and flags.
- Generated artifacts for formats labeled "preview" in the CLI reference.

**Security fixes** are backported to the latest stable minor release. Older
minor versions are not actively patched; upgrade to the latest 1.x.

**Observable conformance** remains the external runtime evidence for
significant emitter or compiler changes. For contributor-accessible conformance,
use the public fixture tracked in issue #107 and documented in
[conformance.md](conformance.md).
