# Compilation cleanup outcomes and real transport recovery

- Source: `72de182a47e1c045f586be73a2c3a79b68f9130b`, following merged PR #895 (`5c7d1353`). [Capture and source pins](evidence/recovery-environment.json), [stdout](evidence/recovery-characterization.txt), [JUnit](evidence/recovery-characterization.xml), [validation](evidence/recovery-validation.json).
- Scope: fix final staging-cleanup outcome classification after normal successful promotion; characterize named native stdio JSON-RPC failures and retry state. Preserve frozen capability/data declarations and historical captures.
- Process feedback: [system-specification #41](https://github.com/ktjn/system-specification/pull/41). The prior [CLI error review](../archived/system-spec-compilation-errors.md) and its plan are archived after merge; the compilation adoption specification remains active.

## Discrepancy and repair

`CompilationService.execute_direct` and `apply` already handled a transaction that raised `FileTransactionCommittedError`. Their normal-success branches called staging removal outside that handler. When removal failed, they raised ordinary `CompilationError` after publication. The filesystem conversation then reported an error and could retain the same pending action despite committed writes.

- Both new service regressions failed with the ordinary exception; the real JSON-RPC regression returned `kind="error"` instead of `applied`. Original red output: [service](evidence/recovery-service-red.txt), [transport](evidence/recovery-rpc-red.txt).
- A shared cleanup helper now wraps failure after normal promotion as the existing `FileTransactionCommittedError`, with exact committed paths, staging path and original cleanup cause. It does not retry promotion or remove committed files.
- Earlier promotion-failure and already-committed-exception behavior remains covered by the existing suite. New tests observe real promotion and staged/destination bytes; only final staging removal is injected.
- Python callers now receive the declared committed-error type for this previously misclassified branch. Internal CLI and filesystem conversation consumers already handle it explicitly: CLI exit 1 with committed writes/cleanup details; conversation `applied` with write/audit metadata and cleanup warning. No editor/protocol implementation or new failure-mode declaration is added.

## Observed wire, disk and retry matrix

These are actual stdio JSON-RPC results using the pinned Python/pygls environment, not inferred codes from exception names. [Tests](../../../../cli/tests/test_lsp_compilation_recovery.py).

| Fault / boundary | Wire result | Disk / pending result | Recovery exercised |
|---|---|---|---|
| Unsupported protocol version | JSON-RPC error `-32603` | Existing stage bytes unchanged; no outputs/audit | Correct version applies the same pending action |
| Missing session ID | JSON-RPC error `-32603` | Original session's stage unchanged; no outputs/audit | Correct session applies the same pending action |
| Wrong action ID | JSON-RPC error `-32603` | Current pending stage unchanged; no outputs/audit | Correct action applies |
| Dirty generated destination | JSON-RPC error `-32603` | Stage unchanged; no publication | Saved/corrected request applies |
| Source changed after preview | Successful RPC containing `kind="error"` | Stage removed; no outputs/audit; pending cleared | Old apply/discard IDs return `-32603`; a fresh preview applies |
| Normal promotion, then staging removal fails | Successful RPC containing `kind="applied"`, committed paths/audit/cleanup warning | Exact preview bytes and audit committed; pending cleared; failed staging survives | Reapply returns `-32603` and does not alter writes; close succeeds but leaves that staging residue |

The last row fixes outcome reporting; it does not establish automatic disposal of failed cleanup. A surviving staging directory is not a pending action or authorization to rerun compilation. Cleanup ownership and crash/durable recovery policy remain review obligations. The unchanged VS Code participant deletes cached previews for `applied` replies; that source fact is not a native editor fault-injection acceptance result. Cached previews after an ordinary domain error remain a separate recovery concern.

## Evidence scope

- Eight new tests pass: direct/apply cleanup regressions and six real stdio transport/recovery cases. Existing CLI committed-error rendering is included in the larger capture.
- Immutable Windows capture: **238 passed, 2 skipped, zero reruns** across the original six compilation suites plus cleanup, transport, CLI error and existing LSP integration suites. Skips are the two directory-symlink privilege cases, retained explicitly.
- Fresh offline Linux capture at the same code revision: **4 passed, 0 skipped**: both named symlink cases and both new service cleanup regressions. [Output](evidence/recovery-linux.txt), [JUnit](evidence/recovery-linux.xml), [environment/command](evidence/recovery-linux-environment.json), [runner](evidence/recovery-linux-run.py).
- Linux reuses the pinned prior dependency image with networking disabled. Current source/tests are exported with explicit `core.autocrlf=false` / `core.eol=lf`, mounted read-only, and checked against Git blobs. The imported implementation path is asserted. Reusing an image is not reusing its old source result.
- Source correspondence checks all 141 previously discovered modules: 140 match; only compilation implementation changed. Its AST imports and all nineteen declared dataclass shapes remain unchanged. The earlier import/type map remains a historical discovery artifact, supported by this bounded correspondence check.
- The [test-only server launcher](../../../../cli/tests/support/lsp_compilation_fault_server.py) controls staging location and patches removal only during apply in its own process. No runtime test hooks, real permission fault, crash proof, every JSON-RPC mapping or manual editor/model acceptance is claimed.

Captured metadata uses a scoped `.gitattributes` `-text` rule. A checkout/export round trip with forced autocrlf verifies exact artifact bytes, including the restored historical mixed-line-ending log; implementation checkout hashes retain their separate host-specific convention. Whitespace attributes preserve the default blank/space checks and recognize CRLF line endings.

## Active and historical records

- [Historical specification](evidence/compilation-before-recovery.yaml) preserves Git bytes from merged `5c7d1353`; [prior manifest](evidence/adoption-before-recovery.json) retains its separate exact-checkout hash convention. Original logs and manifests remain unchanged.
- `EV-02` reserves `supersedes` for failed evidence. Previously passing records are archived and replaced in the active specification, not relabeled failed. The fresh Linux record supersedes only the original failed Windows symlink record; previous Linux passes remain historical.
- Active bindings and ten passing records now name the changed revision: eight original requirement captures refreshed, one extra MOD-COMP-05 cleanup record, and one Linux MOD-COMP-10 record. The two Windows skips are not represented as passes.
- Capability/data versions and declarations remain unchanged. Declared-contract comparison passes; this cannot prove all external Python consumers accept the corrected exception behavior. Public helper/IO catalog correction and consumer disposition remain rework under MOD-COMP-09.

## Gate decision

- Named cleanup-outcome repair and transport/retry characterization: verified for the retained tests and source/environment scope.
- Final-commit native gate and remote build are delivery obligations recorded in the PR, independently of this immutable code capture.
- Keep residual staging ownership, remaining adapter faults, public failure catalog, classification, shared IR semantics, measured quality categories, formal lock/compensation/crash assessment and whole-product release open. Maintainers own acceptance.
