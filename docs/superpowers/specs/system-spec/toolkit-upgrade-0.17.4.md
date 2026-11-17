# Published toolkit 0.17.4 upgrade decision

- Date: 2026-11-17. Previous: [0.5.0 decision](toolkit-upgrade-0.5.0.md).
- Scope: replace the committed offline export `tools/system-spec` with PyPI `system-spec-ref==0.17.4`, update the current schema and agent wiring, and revalidate every active specification. No specification, source binding or evidence capture changed.
- [Package receipt](evidence/toolkit-pypi-0.17.4.json): wheel SHA-256 matches PyPI; all 89 exported files are byte-identical to wheel entries; no vendor edits.

## Gate decision

| Review | Disposition |
|---|---|
| Stage validation | `inventory`, `compilation.yaml` (`verification`), `compilation-contract-proposal.yaml` (`architecture`) and `whole-product.yaml` (`architecture`, `verification`) report `VALID` under both the installed 0.17.4 tool and the offline `metamodel.py` fallback. No metadata migration was required. |
| Artifact checks (`--check-artifacts --root .`) | Hash mismatches are reported on Linux checkouts, identically under the 0.5.0 validator (165 compilation, 18 whole-product at the same HEAD). Pinned hashes bind the Windows CRLF capture bytes; they are not regressions of this upgrade. Evidence was not re-captured and no conformance is claimed. |
| New toolkit material | Added guides: `DOMAIN-AGENTS.md`, `MODERNIZATION.md`, `VERIFIED-DEVELOPMENT.md`, `VERIFIED-DEVELOPMENT-PLAN.md`, `WORKSPACE.md`; skills `ddd`, `lean`; template `MODERNIZATION-DECISION.md`; `reference-implementation/test_evidence_scope.py`. Review [CHANGELOG](../../../../tools/system-spec/CHANGELOG.md) before adopting any new stage or field. |
| Historical preservation | [Prior schema](evidence/schema-before-toolkit-0.17.4.json) and [prior manifest](evidence/adoption-before-toolkit-0.17.4.json) retain exact bytes. [adoption.json](adoption.json) keeps the 0.5.0 record under `previous_toolkit_0_5_0`. |
| Boundaries | Installation and validation do not advance adoption levels, approve the contract proposal or replace native/manual gates. Toolkit version is separate from modeled `system.version`. |

## Remaining work

- Re-capture artifact hashes and evidence on the repository byte convention when a maintainer reruns the characterization suites.
- Assess new 0.17.x features (modernization, verified-development, workspace guides) before use; none is adopted here.
