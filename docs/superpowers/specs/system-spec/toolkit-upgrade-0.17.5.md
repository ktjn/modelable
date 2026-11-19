# Published toolkit 0.17.5 upgrade decision

- Date: 2026-11-19. Previous: [0.17.4 decision](toolkit-upgrade-0.17.4.md).
- Scope: replace the committed offline export `tools/system-spec` with PyPI `system-spec-ref==0.17.5`, revalidate every active specification. Schema and validator are unchanged from 0.17.4; only toolkit guide/skill text changed.
- [Package receipt](evidence/toolkit-pypi-0.17.5.json): wheel SHA-256 matches PyPI; all 89 exported files are byte-identical to wheel entries; no vendor edits.

## Gate decision

| Review | Disposition |
|---|---|
| Stage validation | `inventory`, `compilation.yaml` (`verification`), `compilation-contract-proposal.yaml` (`architecture`) and `whole-product.yaml` (`architecture`, `verification`) report `VALID` under the installed 0.17.5 tool, identically to 0.17.4. `schema.json` and `metamodel.py` are byte-identical to 0.17.4; no metadata migration required. |
| New toolkit material | `CHANGELOG.md`: `modelable` skill re-verified against Modelable 1.16.0 (`.mdl` change kind required, `modelable impact` documented, `validate-compat` exit codes clarified, `selectolax<1` workaround removed). No new guides, stages or fields. |
| Historical preservation | [Prior schema](evidence/schema-before-toolkit-0.17.5.json) and [prior manifest](evidence/adoption-before-toolkit-0.17.5.json) retain exact bytes (identical content to the 0.17.4 state, since no schema change occurred). `adoption.json` keeps the 0.5.0 record under `previous_toolkit_0_5_0`; no separate 0.17.4 record is added, consistent with prior patch-level refreshes that carried no specification change. |
| Boundaries | Installation and validation do not advance adoption levels, approve the contract proposal or replace native/manual gates. Toolkit version is separate from modeled `system.version`. |

## Remaining work

- Re-capture artifact hashes and evidence on the repository byte convention when a maintainer reruns the characterization suites.
