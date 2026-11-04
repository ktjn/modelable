# Whole-product Level 1 draft (dependency and data mapping)

- Date: 2026-11-04. Source: branch `fix/conversation-preview-operational-errors`, Modelable 1.15.2. Spec: [whole-product.yaml](whole-product.yaml); validates with `system-spec docs/superpowers/specs/system-spec/whole-product.yaml --stage architecture --check-artifacts --root .`.
- Status: **draft for maintainer review.** Level 1 is not accepted. The inventory ([inventory.yaml](inventory.yaml)) stays the Level 0 record; the compilation slice stays in [compilation.yaml](compilation.yaml) and is not duplicated.

## What the draft records

| Area | Disposition |
|---|---|
| Capabilities and components | The six inventory components with observed `provides`/`requires` only. Cross-component capabilities carry minimal interfaces (Python API, stdio JSON-RPC, browser dispatch). |
| Data models | Seven models with owners: registry ID ledger, enum-number ledger, registry index DB, snapshot, usage manifest (semantic-toolchain); workspace record, theme preference (browser-playground). Fields come from [registry-protocol-map.md](registry-protocol-map.md), [browser-persistence-map.md](browser-persistence-map.md) and source. |
| Lineage | Only `registry-index-db` derived from `registry-id-ledger` (the index inserts the IDs). Other lineage not traced. |
| Classification | Provisional and conservative (`restricted`; `internal` for the theme flag), each tied to active requirement MOD-ADOPT-03. Not observed product classifications. |
| Boundary waiver | `semantic-toolchain` is a coarse boundary spanning seven source trees and keeps a `max_owns_data: 5` override, with risk `coarse-toolchain-boundary` waiving `context-budget` until release (MOD-ADOPT-04). |

## Known gaps (recorded, not hidden)

- `usage-manifest` and `registry-snapshot` fields are minimal: only the protocol name and snapshot paths were read. `snapshot.py`, resolver, usage graph, Apicurio, OpenLineage, Git source and signature protocols are not mapped in detail.
- Pyodide worker state, AI provider/WebLLM state and model-download state are not modeled as data.
- No external-provider components were declared: external endpoints stay as `external_sources` because no configured endpoint was exercised. OCI is listed as an external source although implementation raises "not implemented".
- No evidence is bound (`evidence: []`); characterization beyond compilation is MOD-ADOPT-02.
- Release-stage diagnostics fail as expected: no requirements per capability, eight missing verification categories, statuses below `verified`.
- Capability pre/post/invariants were written from the maps and tests already cited; they are descriptions, not verified contracts.

## Decision

- **Defer** Level 1 acceptance to maintainers. Do not advance to Level 2/3 for the whole product.
- Observed dependency wiring comes from the inventory; running `--check-drift` reports no drift, but it can miss absolute imports rooted at `cli/src` (see the toolkit upgrade note), so it is not dependency closure.
