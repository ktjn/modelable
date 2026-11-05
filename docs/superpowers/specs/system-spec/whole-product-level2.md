# Whole-product Level 2 draft (behavioral pinning)

- Date: 2026-11-04. Source revision for all evidence: `dbd8807977bafdfdd4981596045a2cbdaab12efb` (clean tree). Spec: [whole-product.yaml](whole-product.yaml) validates at `--stage verification --check-artifacts --root .`.
- Status: **draft for maintainer review; Level 2 is not accepted.** This pins five narrow behaviors, not whole-product conformance.

## Runs ([evidence/level2](evidence/level2))

| Suite | Result | Output |
|---|---|---|
| Python: 13 test modules across browser API/conformance/conversation, LSP conversation/integration/server, CLI compile/errors, registry IDs, file transaction, preview recovery (`-n 0`) | 307 passed, 4 skipped | [txt](evidence/level2/python-level2.txt), [JUnit](evidence/level2/python-level2.xml) |
| Web (vitest): workspace repository, persistent-workspace hook, workspace model, recovery UI | 28 passed, 4 files | [txt](evidence/level2/web-level2.txt) |

- The 2 reruns come from the one `flaky`-marked case in `test_file_transaction.py` (project policy: pytest-rerunfailures with a recorded cause). No cited evidence record uses that test.
- The 4 skips are Windows symlink and POSIX-metadata cases; none is cited as passing evidence.
- Python 3.14.5, pytest 9.1.1, Node v26.13.0, vitest 4.1.10, Windows. No Linux or browser-engine run.

## Pinned behaviors (one named test each)

| Requirement | Capability | Test |
|---|---|---|
| MOD-PROD-01 | local-contract-toolchain | `test_registry_ids.py::test_allocate_never_reassigns_existing_ids` |
| MOD-PROD-02 | native-command-workflows | `test_cli_compilation_errors.py::test_compile_renders_known_operational_errors[ledger-lock]` |
| MOD-PROD-03 | desktop-language-and-conversation | `test_conversation_preview_recovery.py::test_wire_error_keeps_existing_pending_source_action` |
| MOD-PROD-04 | browser-compiler-api | `test_browser_conformance.py::test_native_browser_snapshots_are_deterministic` |
| MOD-PROD-05 | playground-workspace | `workspace-repository.test.ts` "a stale revision cannot overwrite a newer workspace" |

Evidence binds each record to the capability source files it exercises plus the test and output hashes. A tampered source hash is rejected (probe: modifying the `workspace-repository.ts` digest fails the artifact check).

## Gaps and waiver

- **vscode-model-authoring has no passing evidence.** MOD-PROD-06 is `specified` with two criteria; the extension's tests need the VS Code extension host (`npm test` -> `runTests.js`), which was not run.
- **Not pinned:** the stale-save UI behavior found in the [browser map](browser-persistence-map.md) (hook ignores `'stale'`), cross-tab behavior, snapshot/usage/Apicurio/OpenLineage/Git protocols, real WebLLM chat (manual conformance per AGENTS.md), and live integrations.
- **Waiver:** risk `product-category-gap` waives `verification-category` until `verification`, mitigated by MOD-ADOPT-02. Missing categories: serialization, concurrency, performance, scalability, resilience, observability. It blocks release.
- **No compatibility baseline** (`--compat`) was run: the Level 1 spec has no earlier pinned version to compare against.
- Test names pinned are one per criterion; a passing suite count does not establish untested behavior.
- Release stage fails as expected: waiver expiry, six missing categories, unverified ADOPT requirements, statuses below `verified`.

## Decision

- **Defer** Level 2 acceptance to maintainers. Do not advance to Level 3. Next: run the extension-host tests, decide the `'stale'` save policy, then add concurrency/resilience characterization for registry locks and promotion.
