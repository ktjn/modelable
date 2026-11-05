# Browser persistence map (bounded)

- Source: branch `fix/conversation-preview-operational-errors` at `e78a03be`; read from `web/src/{workspace-repository,usePersistentWorkspace,workspace,theme,sw-registration}.ts(x)`, `web/src/App.tsx` (repository wiring), `web/vite.config.ts` and `docs/playground-design.md` §15–16. Observed behavior only; no tests or browser runs were performed for this map.
- Authority: the existing playground design doc, source and native gates. This extends the [inventory](inventory.yaml) "Playground" row; it changes no contract.
- **Not mapped:** the Pyodide worker's in-memory state, the AI/WebLLM session and model-download state (`web/src/ai/**`), and the browser DTO/protocol schemas. Their lifetimes remain open.

## Persistent stores

| Store | Owner | Contents / lifetime |
|---|---|---|
| IndexedDB `modelable-playground`, version 1, object store `workspaces` (keyPath `id`) | `IndexedDbWorkspaceRepository` | One `PlaygroundWorkspace` per id: `schemaVersion` (1), `id`, `revision`, `files[] {path, content, version}`, `activeFile`, optional `metadata.lastAiAccept {provider, model, timestamp}`. Source of truth for user source; survives reloads. |
| `localStorage` key `modelable:theme` | `theme.ts` | `'light'` or `'dark'`; absence means `system`. Reads/writes are wrapped in try/catch (storage may be disabled). |
| Service worker + Workbox precache | `vite-plugin-pwa` in `vite.config.ts` | `registerType: 'autoUpdate'`, scope `/modelable/playground/`; precaches `js, css, html, wasm, mjs, zip, json, whl, ttf, woff, woff2, png` (excluding `fixtures/**`, files up to 30 MB), navigate fallback to `index.html`. Holds app and Pyodide assets, not user data. |

Derived results (compiled artifacts, diagnostics, graph) are memory-only; the design doc says the same (§ around line 1041).

## Repository protocol

| Operation | Observed behavior |
|---|---|
| `load(id)` | Readonly transaction. `missing` if absent; `ready` with the parsed workspace; `recovery-required` (`invalid` or `incompatible`, carrying the raw record) when `parseWorkspaceRecord` throws `WorkspaceValidationError`. Other errors propagate. Unsupported `schemaVersion` -> `incompatible`. |
| `save(workspace)` | Readwrite transaction; reads the stored record and returns `'stale'` without writing only if the stored `revision` is **greater** than the one being saved. Equal or lower stored revision is overwritten. Writes a `structuredClone`. |
| `remove(id)` | Deletes the record. |
| Schema upgrade | `onupgradeneeded` creates the `workspaces` store if missing. There is no migration path beyond version 1; a different stored `schemaVersion` is surfaced for recovery rather than migrated. |

## Hook protocol (`usePersistentWorkspace`)

- Phases: `restoring`, `saving`, `saved`, `memory-only`, `recovery-required`.
- On mount: `load(default id)`; `missing` -> adopt the default workspace and save immediately; `recovery-required` -> hold the raw record and block normal editing; load rejection -> `memory-only`.
- Edits: set dirty, debounce 300 ms, then save; a monotonic sequence number and the current revision gate the `saved` transition so a late older save cannot mark a newer edit as saved.
- `pagehide` with unsaved changes triggers an un-awaited save.
- Save rejection (including IndexedDB unavailable) -> `memory-only`; no automatic retry was found.

## Observations for follow-up (from reading source, not confirmed by tests)

- **`'stale'` result (fixed after this map was drafted: the hook now enters `memory-only`; the paragraph below describes the earlier behavior).** The hook awaits `repository.save(snapshot)` without inspecting its return value, so a `'stale'` result is treated the same as `'saved'` (phase becomes `saved` if the in-memory revision still matches). With two tabs on the same workspace id, the lower-revision tab's save is rejected by the repository but shown as saved. No test in `usePersistentWorkspace.test.tsx` references a `'stale'` save result (grep); repository-level behavior is tested in `workspace-repository.test.ts`. Maintainers should decide the intended UI state before treating this as a defect.
- **Cross-tab notification (added after this map was drafted: the hook now uses a `BroadcastChannel` to announce saved revisions; the sentence below describes the earlier behavior).** Equal-revision overwrite: two tabs at the same revision overwrite each other; there is no cross-tab notification (grep found no `BroadcastChannel` or `storage` listener in `web/src`).
- **Unmount drops a pending debounce.** The effect cleanup clears the timer without flushing; only `pagehide` flushes. An unmount that is not a page unload would lose the last debounced edit.
- **`pagehide` save is best effort.** The IndexedDB write is not awaited by the browser lifecycle, so completion is not guaranteed.
- **Design-doc drift.** `docs/playground-design.md` lists IndexedDB stores for editor state, cached compiler metadata, graph layouts and model download state; the only store in code is `workspaces`. Record as an as-is discrepancy rather than a missing requirement until maintainers confirm which is authoritative.
- **Service-worker update safety.** The design doc requires that an update must not silently invalidate unsaved state; the config uses `autoUpdate`. Whether an update reloads the page while the workspace is dirty was not verified here.
- **Secrets.** `metadata.lastAiAccept` stores provider/model names only; the design doc forbids secrets in IndexedDB/`localStorage`. No secret storage was found in the files read, but `web/src/ai/**` was not searched exhaustively beyond a storage-API grep, which found none.

## Disposition

- Accepted as a bounded observed map of workspace persistence. Classification of stored data remains open: workspace content is user source text and should be treated as at least the compilation DTOs' provisional `restricted` handling; this is not an observed product classification.
- Candidate follow-ups for maintainers to schedule: a test and decision for handling `'stale'` saves; a decision on cross-tab behavior; confirmation of the service-worker update/dirty-state behavior; reconciling the design doc's store list with the code.
