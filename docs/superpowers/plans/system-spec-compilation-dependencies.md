# Compilation dependency and ownership discovery

- Scope: archive the merged migration plan; map compilation's direct/transitive source dependencies, nested DTO/state ownership and operation side effects; attempt the two missing directory-symlink cases on a suitable Linux filesystem.
- Preserve the original whole-product inventory and historical evidence. Python compilation behavior remains pinned to `8de5b55bf07cff4a619c6ae25f2c3368290d310b`; current discovery starts from merged Modelable main `3379c7c6`.
- Work in the existing checkouts, using separate Modelable and system-spec feedback branches.

## TODO

- [x] Refresh merged main, instructions, existing authorities and acceptance gaps.
- [x] Archive the completed evidence migration plan; keep the ongoing onboarding specification active.
- [x] Trace operation transitions, nested types, source imports and state owners.
- [x] Capture a source-bound dependency/ownership map with explicit external and deferred boundaries.
- [x] Run the missing symlink checks on a suitable host; retain historical skips and report actual results.
- [x] Validate specification compatibility, artifact bindings and changed documentation.
- [x] Feed new findings back to system-specification.
- [x] Run mandatory precommit checks and prepare exact-commit native-gate delivery.

## Acceptance

- Mapping names actual symbols, source paths, providers, state/transaction owners and exceptional side effects; it does not invent deployed services or treat a static import graph as a runtime call graph.
- Any newly passing symlink evidence covers both named tests on the pinned source and explicitly supersedes only the historical partial record. No failed/omitted/skipped check becomes a pass.
- Retain the original contract unless observed behavior proves a correction necessary. Whole-product and release acceptance remain open.
- Native gates remain mandatory; PR descriptions/checks record publication and remote CI separately.

Provenance correction: the first Git export inherited Windows autocrlf. Its tests passed, but its descriptive byte convention was incorrect. The retained active capture was rebuilt with explicit LF export, verified against Git blobs and rerun: two passed, zero skipped. The original scratch run remains available locally.

Local validation: compatibility, inventory/verification artifact checks, nineteen dataclass field inventories and four negative evidence probes passed. Ruff format/check and mypy baseline passed; Python 3,182 passed, 67 skipped. Feedback is published in system-specification PR #39. Full native push and remote CI are recorded separately in the delivery PR.
