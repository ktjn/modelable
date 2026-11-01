# Published toolkit onboarding decision

- Date: 2026-11-01. Scope: tool installation, offline instructions and verifier migration for the existing brownfield adoption.
- Baseline: Modelable #897 merged at `cd1c59aca64aea8c22c1cf10fb0be6ff0696d48f`. The completed proposal-preparation plan is archived; consumer implementation and acceptance remain open.
- Authority: follow [WIRING](../../../../tools/system-spec/WIRING.md), [CONSTITUTION](../../../../tools/system-spec/CONSTITUTION.md) and [BROWNFIELD](../../../../tools/system-spec/BROWNFIELD.md). Existing project specs and decisions stay here; the example `system-spec/spec.yaml` path does not create a second baseline.

## Installation and snapshot

- Installed `system-spec-ref==0.1.0` from PyPI using `uv tool install --index-url https://pypi.org/simple system-spec-ref==0.1.0`; installed `system-spec --version` reports `0.1.0`.
- Verified the downloaded wheel against PyPI's SHA256 and all 47 installed package modules/resources against that wheel. Exported all 44 toolkit files intact to `tools/system-spec`; all match the wheel, with 182 local Markdown links checked and none missing.
- [Package receipt](evidence/toolkit-pypi-0.1.0.json) records wheel origin/digest, dependency versions, export file hashes and current verifier/schema hashes. Scoped Git attributes preserve the published payload bytes; staged blobs, forced-autocrlf checkout and archive all match the receipt. Do not reformat vendor files.
- Standalone exported `--version` reports `0.0.0+unknown` without installed distribution metadata. Identify this snapshot by the receipt's package, wheel and file hashes. Package version is separate from modeled contract versions.
- [Agent instructions](../../../../AGENTS.md) point to the published track and conditional TLA+/Alloy/Modelable guides. Their tools remain separate prerequisites. No global skill activation is needed.

## Gate decision

| Gate | Evidence and disposition |
|---|---|
| Published/offline parity | Seven command/result pairs match: inventory, compilation verification, proposal architecture, compatibility rejection, release rejection, bounded context and impact. [Validation capture](evidence/packaged-toolkit-validation.json). |
| Existing active specs | Inventory/inventory, compilation/verification and proposal/architecture pass with repository artifact checks. The existing compilation category waiver remains. Exact commands and offline fallback: [README](README.md#validation-and-bounded-work). |
| Verifier migration | Schema is semantically identical to the historical pinned schema. AST comparison finds only added `diagram` and changed CLI `main`; validation, compatibility and artifact functions are unchanged. Historical adoption/source/schema/evidence pins remain untouched. |
| Packaged reference tests | 124 passed, 1 skipped (file symlinks unavailable on this host); no failures. [Text](evidence/packaged-toolkit-tests.txt), [JUnit](evidence/packaged-toolkit-tests.xml), exact command/environment in the receipt. This is verifier testing, not product runtime evidence. |
| Contract proposal | Still unaccepted; three expected `COMPAT-04` diagnostics remain against the active contract. Merging proposal documentation does not activate modeled 2.0. |
| Adoption/release | Whole-product Level 0 intake and bounded compilation Levels 1–2 retain their existing limits. Compilation release, whole-product Levels 1–3, formal applicability and outstanding consumer/manual acceptance remain open. |
| Delivery | Native precommit/prepush gates remain mandatory and separate. Exact-commit results and remote CI belong in the delivery PR; package installation does not establish them. |

Decision: published-tool wiring is verified within this scope. No adoption level, contract acceptance or release decision is advanced. Maintainers own the remaining acceptance gates.

## Upgrade and feedback

- Install a reviewed pinned release; export to a new absent destination, compare the full tree and provenance, update agent paths, and revalidate every active spec at its existing stage with artifact checks.
- Retain historical verifier/source/evidence decisions. A changed package does not relabel old captures; assess schema/validation changes before reusing evidence.
- Keep the exported snapshot intact. Upstream [PR #50](https://github.com/ktjn/system-specification/pull/50) implements WIRING/feedback improvements for a future release: reuse existing authoritative spec paths, record published/offline provenance and byte policy, explain standalone version metadata, and preserve adoption gates during upgrades.

- Diff hygiene: the intact published `archive/REVIEW.md:3` contains a Markdown hard-break (two trailing spaces). It is retained byte-for-byte; no vendor whitespace assertions or hashes are changed. Project-authored edits pass the separate whitespace check.
