# Published toolkit 0.4.0 upgrade decision

- Date: 2026-11-01. Baseline: Modelable #902 merged at `0aa1949afea74e4ba1daa17c312996b7982caa29`.
- Scope: import PyPI `system-spec-ref==0.4.0`, update the current schema and agent wiring, and adopt observed test/criterion/environment metadata. Follow [WIRING](../../../../tools/system-spec/WIRING.md), [CONSTITUTION](../../../../tools/system-spec/CONSTITUTION.md), [BROWNFIELD](../../../../tools/system-spec/BROWNFIELD.md) and [FEATURE](../../../../tools/system-spec/FEATURE.md).
- [Package receipt](evidence/toolkit-pypi-0.4.0.json): wheel SHA-256 matches PyPI, all 65 installed package files and all 62 exported files match the wheel. The committed toolkit has no vendor edits or generated Python caches. Prior [0.2.0 decision](toolkit-upgrade-0.2.0.md) and package receipts remain historical.

## Gate decision

| Review | Evidence / disposition |
|---|---|
| New toolkit features | Test/fake bindings, feature workflow, provider-first planning and scope guards (0.3); split specs, structured returns, criterion evidence, domains/external/imported/mediated providers, JS/TS drift and catalog exports (0.4). Full [release history](../../../../tools/system-spec/CHANGELOG.md) is imported. |
| Selected metadata | Compilation declares its two existing evidence-provenance test modules and assembly scope. Existing single-criterion records gain exact criterion strings and observed Windows/Linux environments. No new criterion or passing execution is asserted. All contract sections, requirements, risks and source bindings are identical to the prior spec. |
| Provenance migration | With test paths enabled, `COMP-08` correctly rejects the Linux record's log-file provenance. It now names `cli/tests/test_compilation_service.py`, which contains both executed symlink cases. Original JUnit/log/environment hashes, source revision, date and verifier remain intact. No log directory is disguised as a test path. |
| Historical preservation | [Prior spec](evidence/compilation-before-toolkit-0.4.0.yaml), [schema](evidence/schema-before-toolkit-0.4.0.json) and [manifest](evidence/adoption-before-toolkit-0.4.0.json) retain exact bytes. Current [manifest](adoption.json) separates original execution/verifier pins from the new toolkit and refreshed metadata hashes. No passing record is falsely superseded. |
| Current stages | Inventory/inventory, compilation/verification and proposal/architecture pass with artifact checks. Metadata migration compatibility passes. Proposal comparison retains exactly three `COMPAT-04` diagnostics; compilation release fails on existing obligations. |
| Tool verification | All three generated schemas match the publication. Reference suite: 184 passed, two host file-symlink skips; [text](evidence/packaged-toolkit-tests-0.4.0.txt), [JUnit](evidence/packaged-toolkit-tests-0.4.0.xml). These verify the toolkit, not Modelable product behavior. |
| Feature diagnostics | [Capture](evidence/packaged-toolkit-validation-0.4.0.json): 16 installed/offline pairs agree, including plan, context, impact, Mermaid, Backstage/Structurizr and structured returns. Seven probes verify owned/rejected paths, missing return obligations, stale versions, invalid criteria and log/test provenance distinction. |
| Handoff semantics | The [template](handoff-return-template.yaml) deliberately returns every applicable obligation unmet and no passing results. `--check-return` accepts accountable incompleteness; it does not grant acceptance. System-targeted MOD-COMP-09 remains separately open. |
| Export links | Reviewed 300 local Markdown targets: 299 resolve; published `PACKAGING.md` links to absent `RELEASING.md`. Keep the snapshot exact, use the [upstream release guide](https://github.com/ktjn/system-specification/blob/main/RELEASING.md), and repair the link upstream for future exports. |
| Diagnostics limits | Drift still uses a separate command branch and can miss absolute imports rooted at `cli/src`; a clean result is not dependency closure. Generated Backstage owner remains unknown and catalog output is not a deployment claim. |
| Boundary decisions | Keep the coherent compilation spec together. Split files, domains, imports, external providers, mediation and fakes need separately reviewed ownership/runtime/isolation facts. No new dependency, product runtime change, activation or acceptance level is introduced. |
| Delivery | Mandatory precommit and exact-commit native gates remain required. Actual publication and remote CI results belong in the delivery PR. |

## Feedback and remaining work

- Upstream feedback records the provenance migration, all-unmet return semantics and the need to keep source/evidence identity distinct from current schema wiring. The delivery PR links its publication.
- Shared service source hashes, candidate contract, historical execution artifacts and inventory facts remain unchanged. The root README diagram is regenerated verbatim with 0.4.0's kind-prefixed IDs.
- External Python consumers, other operational faults, cleanup/crash ownership, stale-apply cache policy, manual/model UI acceptance, shared IR/classification/formal/quality and release decisions remain open. This tooling upgrade closes none of them.
