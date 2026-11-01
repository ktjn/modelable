# Published toolkit 0.2.0 upgrade decision

- Date: 2026-11-01. Scope: installed tool, intact offline snapshot and current instructions; baseline Modelable #898 merged at `06c1765cf4ce74c6f496a9a319acc7b8ed8a5a2c`.
- Follow exported [WIRING](../../../../tools/system-spec/WIRING.md), [CONSTITUTION](../../../../tools/system-spec/CONSTITUTION.md) and [BROWNFIELD](../../../../tools/system-spec/BROWNFIELD.md). Existing project specs remain authoritative. [Exact current commands](README.md#validation-and-bounded-work) and [agent instructions](../../../../AGENTS.md) pin `system-spec-ref==0.2.0`.
- Installed tool already reported 0.2.0; explicit pinned installation against PyPI confirmed it. Downloaded wheel SHA-256 matches PyPI; all 47 installed files and all 44 fresh-export files match the wheel. The committed snapshot is copied from that verified fresh export without vendor edits.
- [0.2.0 package receipt](evidence/toolkit-pypi-0.2.0.json) records wheel/source identity, dependencies, all export hashes and test results. [0.1.0 receipt](evidence/toolkit-pypi-0.1.0.json) and [original onboarding decision](pypi-onboarding.md) remain historical. Standalone exported version metadata remains unavailable; receipt hashes identify the snapshot.

## Gate decision

| Review | Evidence / disposition |
|---|---|
| Schema/validator | Schema is unchanged. AST comparison finds only added `check_drift` and changed CLI `main`; existing model, validation, compatibility and artifact functions are unchanged. No model migration or historical evidence relabeling. |
| Current stages | Inventory/inventory, compilation/verification and proposal/architecture pass with artifact checks. [Seven installed/offline command pairs](evidence/packaged-toolkit-validation-0.2.0.json) also match 0.1.0 exactly, including context/impact and expected compatibility/release failures. |
| Reference tests | 131 passed, 2 skipped because file symlinks are unavailable on this host; no failures. [Text](evidence/packaged-toolkit-tests-0.2.0.txt), [JUnit](evidence/packaged-toolkit-tests-0.2.0.xml), exact command in receipt. These test the verifier, not Modelable product acceptance. |
| Optional drift diagnostic | [Capture](evidence/packaged-toolkit-drift-0.2.0.json) returns valid even with `--stage release`, while ordinary release validation correctly fails. Drift selects a separate branch and does not run stage validation. Absolute imports resolve only at root/root-src; Modelable uses `cli/src`, and unresolved imports are not listed as unchecked. Keep normal stage/artifact gates separate; this result does not establish dependency closure. |
| Export links | 185 of 186 local Markdown targets resolve. Published README links to absent `PYPI.md`; snapshot remains exact. Upstream [PyPI source document](https://github.com/ktjn/system-specification/blob/main/PYPI.md) is the fallback. |
| Open acceptance | Proposal remains unaccepted with three `COMPAT-04` diagnostics; active contract/source/evidence bindings stay unchanged. Existing compilation category waiver, release blockers, whole-product adoption, formal review and consumer/manual obligations remain open. |
| Delivery | Mandatory precommit and exact-commit native prepush gates remain required. Actual results and remote CI belong in the delivery PR. No runtime/API/dependency change is introduced. |

Decision: update the toolkit pin and current wiring within the existing adoption scope. Installation and validation do not advance contract/adoption/release acceptance; maintainers retain those decisions.

## Feedback and preservation

- [System-spec PR #54](https://github.com/ktjn/system-specification/pull/54) documents drift-only semantics and monorepo import-resolution limits, fixes the upstream README link for future exports, and records the findings. The current 0.2.0 export is unchanged.
- Existing scoped `-text` Git attributes preserve published bytes. All 44 staged blobs must match the receipt through forced-autocrlf checkout and archive before commit. The published archive review's Markdown hard-break remains intact; project-authored files receive separate whitespace checks.
- Newer instructions now include prior onboarding feedback: authoritative spec paths, reproducible provenance and historical-evidence preservation. Optional formal-tool guides remain in the intact tree with separate prerequisites.
- For the next upgrade, install a reviewed pinned version, export to a fresh absent destination, compare schema/behavior/file identities, recapture validation at existing stages, retain historical receipts and feed new gaps upstream.
