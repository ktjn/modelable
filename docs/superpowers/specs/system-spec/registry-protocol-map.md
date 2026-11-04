# Registry shared-protocol map (bounded)

- Source: branch `fix/conversation-preview-operational-errors` on `b6176914`; read from `cli/src/modelable/registry/{base,factory,local,oci,ids,enum_numbers,index}.py`, `schema.sql` and `operations/compilation.py`. Observed behavior only; no tests were run for this map.
- Authority: existing source, [architecture](../../../architecture.md) and native gates. This extends the [compilation map](compilation-map.md); it does not change any frozen contract.
- **Not mapped:** `snapshot.py` (2704 lines), `resolver.py`, `usage*.py`, `apicurio.py`, `openlineage.py`, `sources.py`, `signature.py`. Snapshot, usage and external-publication protocols remain open.

## Registry transport (index push/pull)

| Piece | Observed behavior |
|---|---|
| `Registry` (ABC, `base.py`) | `push(registry_path)` / `pull(dest_path)` of a registry index file. |
| `get_registry` (`factory.py`) | `oci://` prefix -> `OCIRegistry`; anything else -> `LocalRegistry(Path)`. |
| `LocalRegistry` | `push`: creates parent dirs, `copy2` unless source and destination resolve identically. `pull`: `copy2` unless identical. Plain copy: no lock, no temp-file-and-replace, no hash check. |
| `OCIRegistry` | Both operations raise `OCIRegistryError` ("not implemented"). Consistent with the compilation map: no remote OCI commit exists to roll back. |

## Local state owned by the registry package

| State | Writer | Notes |
|---|---|---|
| `registry.db` (SQLite) | `build_registry` in `index.py` | Rebuildable index: deletes any existing file, runs `schema.sql` (15 tables incl. `registry_ids`), inserts workspace content, commits. Not incremental; not guarded by `RegistryIdLock`. |
| Registry-ID ledger (JSON `name -> int`) | `write_lock_file` in `ids.py` | Temp file in same dir, `fsync`, `os.replace`. IDs are never reassigned or reused; orphaned IDs raise `ValueError` unless `allow_orphaned`. |
| Enum-number ledger (JSON, per-declaration members + reservations) | `write_lock_file` in `enum_numbers.py` | Same temp/fsync/replace pattern. Removed members become reservations; a reappearing removed name raises `EnumNumberConflictError`. |
| Ledger lock (`.<ledger-name>.lock`) | `RegistryIdLock` in `ids.py` | `O_CREAT|O_EXCL` file holding the PID; polls every 10 ms up to 30 s, then `RegistryIdLockContentionError`. Stale locks reclaimed when the recorded PID is not alive (Windows `OpenProcess`/`GetExitCodeProcess`, POSIX `kill(pid, 0)`). Release retries `unlink` 20 times, then renames to `.released-<uuid>` and deletes best-effort. |

`RegistryIdLock` is a generic per-path lock despite its name; compilation uses it for both ledgers.

## Observations relevant to MOD-COMP-09 formal review

These are observations from reading source, not defects confirmed by a test.

- **Lock asymmetry.** `execute_direct` (`compilation.py:285-288`) holds the registry-ID lock then the enum-number lock. `apply` (`compilation.py:507`) holds only the registry-ID lock; ID-ledger freshness is checked by equality with `registry_ids_before`, and other files by `_verify_apply_freshness`. Whether enum-ledger changes during apply are always caught by that fingerprint check, and whether a concurrent direct run can interleave, needs targeted review or a model; the existing tests do not state it.
- **Lock order.** Only one order (ID, then enum) is observed in direct execution; no code path takes them in the reverse order. Workspace promotion lock (`.modelable/locks/compilation.lock`) is taken inside, via `FileTransaction`. Nesting order ID -> enum -> workspace is the candidate invariant.
- **PID-based reclamation.** A recycled PID can make a dead owner's lock look live (blocks until timeout); nothing in the code excludes a race where a stale lock is read, a new owner recreates it, and the old reader then unlinks the new lock. Both are crash/race windows, not proven.
- **Non-atomic index/transport.** `build_registry` unlinks the old `registry.db` before rebuilding, and `LocalRegistry` copies in place; an interrupted run can leave a missing or partial file. Not exercised by the compilation characterization.
- **Contention surface.** `RegistryIdLockContentionError` and `LockContentionError` are not in the frozen `failure_modes`; conversation preview now translates them (see the compilation map), while service contract and LSP wire behavior are unchanged.

## Disposition

- Accepted as a bounded observed map for the pieces compilation touches. Not accepted: snapshot, usage, resolver, Apicurio/OpenLineage and signature protocols; browser persistence (IndexedDB workspace, service worker) is the next map.
- Candidate follow-ups, for maintainers to schedule: a targeted test for enum-ledger change between preview and apply; a lock-order/freshness model under the formal-review requirement; a decision on atomic replace for `LocalRegistry.push` and `build_registry`.
