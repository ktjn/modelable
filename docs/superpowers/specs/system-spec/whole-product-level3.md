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

- **Formal model:** no TLA+ model was written or checked. `tlc`/`tla2tools` are not installed (Java exists); downloading the jar needs your approval, and an unchecked model would not be evidence. Lock-ordering, freshness and rollback formal applicability stays open.
- **Native and manual gates:** the full pre-push gate, `run_browser_playground.py`, and the manual real-model WebLLM chat conformance (needs WebGPU hardware) were not run.
- **Evidence strength:** each record is one test per criterion on Windows only; the concurrency test is a process-level lock test, not a proof of ordering or crash safety.
- **Product discrepancies still open:** playground hook ignores `'stale'` saves; apply holds only the registry-ID lock (see the [registry](registry-protocol-map.md) and [browser](browser-persistence-map.md) maps).

## Decision

- **Level 3 is not accepted and cannot be claimed.** Release needs zero waivers, all ten categories and `verified` statuses; three categories, two waivers and several requirements remain.
