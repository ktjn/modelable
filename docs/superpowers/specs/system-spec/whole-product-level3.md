# Whole-product Level 3 readiness (not accepted)

- Date: 2026-11-04. Evidence source revision `dbd8807977bafdfdd4981596045a2cbdaab12efb`, reusing the [Level 2 run](evidence/level2/python-level2.txt) (300 passed, 4 skipped, 2 reruns from the flaky-marked case, which is not cited). Spec: [whole-product.yaml](whole-product.yaml) validates at `verification`; **`release` still fails.**

## Progress in this step

Three more requirements on `local-contract-toolchain`, each one named passing test with source-bound evidence (MOD-PROD-07..09):

| Category | Test |
|---|---|
| serialization | `test_registry_ids.py::test_write_then_read_lock_file_round_trips_sorted_by_id` |
| concurrency | `test_registry_ids.py::test_registry_id_lock_serializes_processes` |
| resilience | `test_file_transaction.py::test_transaction_verifies_promoted_hash_and_rolls_back` |

Release diagnostics dropped from six missing verification categories to three. `file_transaction.py` was added to the capability's source binding.

## Remaining release blockers (from `--stage release`)

| Blocker | Owner / needed |
|---|---|
| Missing categories: performance, scalability, observability | Maintainers define measurable targets; no measurements exist. Waiver `product-category-gap` (expires at `verification`) cannot remain at release. |
| Waiver `coarse-toolchain-boundary` (context-budget) | Discover finer `semantic-toolchain` boundaries (MOD-ADOPT-04). |
| MOD-ADOPT-01..04 and MOD-PROD-06 lack evidence | Complete discovery maps, classification review (MOD-ADOPT-03), VS Code extension-host tests. |
| Capability, component and system status below `verified` | Follows from the above. |

## Not done, and why

- **Formal model:** now done as a bounded TLC model; see the next section. Crash-atomicity and failed-compensation behavior are not guaranteed by the observed protocol.
- **Native and manual gates:** the full pre-push gate, `run_browser_playground.py`, and the manual real-model WebLLM chat conformance (needs WebGPU hardware) were not run.
- **Evidence strength:** each record is one test per criterion on Windows only; the concurrency test is a process-level lock test, not a proof of ordering or crash safety.
- **Product discrepancies still open:** playground hook ignores `'stale'` saves; apply holds only the registry-ID lock (see the [registry](registry-protocol-map.md) and [browser](browser-persistence-map.md) maps).

## Formal model (TLA+ / TLC)

- Files: [CompilationProtocol.tla](evidence/formal/CompilationProtocol.tla), four `.cfg` files and [tlc-output.txt](evidence/formal/tlc-output.txt) under `evidence/formal`. Tool: `tla2tools.jar` v1.7.4 (TLC 2.19, OpenJDK 25.0.5) downloaded from the `tlaplus/tlaplus` GitHub release into a directory outside the repository, size 2274532 bytes, SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88` (the release publishes no digest, so this is a self-computed fingerprint, not a verified checksum). The jar is not committed.
- Model: two processes (direct, apply), two destination files, ID/enum/workspace locks, freshness checks, per-file promotion, failure and compensation, optional crash. Assumptions (abstractions, crash releases locks, rollback restores previous version) are in the module header.
- Results: config A (no faults) and D (compensation may fail and crash; safety invariants) pass, 171 and 530 states, no deadlock reported. Config B (compensation may fail) and C (crash mid-promotion) violate `FilesConsistent`: destination files can end in different versions. Reachability probes show apply can commit, be rejected, and direct can commit; a mutant with both freshness checks removed violates `NoLostUpdate`.
- Spec binding: MOD-PROD-10 (concurrency, `model-check`, passed) and MOD-PROD-11 (resilience, failing evidence, release blocker REQ-04) in [whole-product.yaml](whole-product.yaml). Risk `promotion-not-crash-atomic` tracks the gap.
- Reading: with locks as observed, a preview-based apply and a conflicting direct run cannot both commit in the bounded model; the earlier question about apply not holding the enum lock is covered because freshness compares every destination under the workspace lock. The model abstracts away code; a model pass is not proof of the implementation, and the freshness comparison was modeled from `_verify_freshness` as read, not run.

## Decision

- **Level 3 is not accepted and cannot be claimed.** Release needs zero waivers, all ten categories and `verified` statuses; three categories, two waivers and several requirements remain.
