# 2026-08-02 Playground Error Handling & WebLLM Tiered Recommendations Design

## Goal

Tighten error handling across the web playground (`web/src`) — a React error boundary, a toast notification system, a typed AI provider error, and a shared error-normalization helper — and replace WebLLM's single "best fit" model recommendation with a curated fast/balanced/quality tier recommendation while keeping every fetched model in the selector.

## Decisions

- Error handling and the WebLLM tiering change are scoped to `web/src` only. `cli/` (Python LSP/CLI) uses an unrelated error convention and is out of scope.
- A new `web/src/errors.ts` exports `toErrorMessage(error: unknown, fallback: string): string`, replacing the duplicated `error instanceof Error ? error.message : 'fallback'` checks in `App.tsx` (handleAiDownload, handleAiFetchModels) and `ai.worker.ts` (handleListModels and other catch sites).
- A new `AiProviderError extends Error` class (mirroring `BrowserCompilerError` in `protocol.ts`) carries a code from `'WEBGPU_UNSUPPORTED' | 'MODEL_LIST_FAILED' | 'INITIALIZATION_FAILED' | 'COMPLETION_FAILED' | 'FETCH_MODELS_FAILED' | 'PROVIDER_DISPOSED'`. The worker's `{type:'error', message}` response gains an optional `code` field; `WebGpuProvider` wraps rejections in `AiProviderError` using that code (defaulting to `INITIALIZATION_FAILED`/`COMPLETION_FAILED` by call site when the worker omits one).
- A new toast system (`web/src/Toast.tsx`) provides `ToastProvider` + `useToasts()` (context/reducer) and a `ToastContainer`, mounted once near the root in `App.tsx`. Toasts support `error` | `warning` | `info` variants, auto-dismiss after a timeout, manual close, and stack multiple simultaneous toasts. Toasts are for *transient* failures; the existing status chip and inline diagnostics remain for *persistent* state and are not removed or replaced.
- A React `ErrorBoundary` (`web/src/ErrorBoundary.tsx`) wraps the app at the `main.tsx` mount point with a minimal fallback UI (message + reload button), so a render-time exception no longer blanks the page silently.
- Concrete gaps fixed as part of this work:
  - `App.tsx`'s `WebGpuProvider.getWebLlmModels().then(...)` (currently missing a `.catch()`) gets error handling that pushes an error toast and dispatches an AI error action.
  - The dead, unused `const allModels = [...models];` line in that same effect is removed.
- `suggestModel(models, limits): string` in `webgpu-provider.ts` is replaced by `suggestModels(models, limits): { fast?: string; balanced?: string; quality?: string }`. Using the same GPU-fit filter as today, it assigns the smallest-VRAM fitting model to `fast`, the largest-VRAM fitting model to `quality`, and the fitting model whose VRAM is closest to the midpoint of that range to `balanced`. When fewer than 3 distinct models fit, tiers collapse (e.g. only `fast` is set for a single fitting model; `fast`/`quality` only for two).
- Tier assignment is computed purely from the VRAM-fit position within the already-fetched dynamic model list (`prebuiltAppConfig.model_list`) — no model IDs are hardcoded — so it stays correct across `web-llm` version bumps that change which models are offered.
- `ModelOption.recommended?: boolean` becomes `ModelOption.recommendedTier?: 'fast' | 'balanced' | 'quality'`. All fetched models remain in the dropdown; nothing is filtered out. `ChatPanel.tsx`'s `<option>` label renders `(Recommended · Fast)` / `· Balanced` / `· Quality` for tiered entries, sorted with recommended tiers first (fast, balanced, quality order) then the rest by ascending VRAM, matching current sort behavior.

## Architecture

`errors.ts` and the new `AiProviderError` sit under `web/src/ai/` (colocated with the provider code that throws them) except the generic `toErrorMessage` helper, which lives at `web/src/errors.ts` since `App.tsx` (outside `ai/`) also uses it for non-AI catches. `Toast.tsx` and `ErrorBoundary.tsx` live at `web/src/` top level as app-wide UI infrastructure, not AI-specific. `App.tsx` mounts `ToastProvider` once, and effect/callback catch sites (`handleAiDownload`, `handleAiFetchModels`, the `getWebLlmModels().then()` chain, and equivalent worker-facing catches) call `useToasts().push(...)` alongside existing `aiDispatch({ type: 'error', ... })` calls — the reducer/status-chip path is unchanged, toasts are additive. `main.tsx` wraps the existing `<App />` render in `<ErrorBoundary>`.

`suggestModels` replaces `suggestModel` at its one call site in `App.tsx`'s WebGPU-detection effect; the effect maps `recommendedTier` onto each model in `setModels` instead of a boolean `recommended`, and picks the `fast` tier's model id as the auto-selected model (preserving current behavior of auto-selecting the safest small option when no `?model=` param is present).

## Error handling and safety

- `AiProviderError` and `toErrorMessage` never leak raw non-Error thrown values (e.g. strings, plain objects) into the UI unprocessed — they're always normalized to a message string with a safe fallback.
- The `ErrorBoundary` fallback does not expose stack traces or internals to the user by default; it logs the error to `console.error` for local debugging and shows only a generic message + reload action.
- Toasts never render raw HTML from error messages (text content only), consistent with the project's existing no-injected-HTML pattern for diagnostics.
- The `getWebLlmModels()` fix ensures a worker failure while listing models surfaces a toast and leaves `aiState` in a recoverable `error` status rather than leaving the UI stuck mid-detection with no feedback.
- Tier computation (`suggestModels`) has no fitting models as a valid, handled case (returns `{}`), matching today's existing fallback in the caller (small hardcoded default `Qwen2.5-0.5B-Instruct-q4f16_1-MLC` id remains the ultimate fallback when `limits === null`).

## Testing and acceptance

- Unit tests for `toErrorMessage` (Error, non-Error, undefined inputs).
- Unit tests for `suggestModels`: no limits, no fitting models, 1/2/3+ fitting models, tie-breaking when VRAM values are equal.
- Component test (or manual verification) that `ErrorBoundary` renders its fallback when a child throws, and that `ToastContainer` renders and auto-dismisses a pushed toast.
- Manual verification in a WebGPU-capable browser: trigger a model-list failure (e.g. by temporarily throwing in the worker) and confirm a toast appears instead of a silent unhandled rejection.
- Existing playground/browser compiler test suite and lint/typecheck remain green; `recommended` → `recommendedTier` rename is applied consistently across `webgpu-provider.ts`, `App.tsx`, and `ChatPanel.tsx` with no leftover references to the old field.

## ADR impact

No new ADR required. This is UI-infrastructure hardening and a selection-algorithm change within the already-accepted playground/WebGPU-provider architecture; it does not change the browser protocol, worker boundary, or persistence model.

## Non-goals

- Changes to CLI/LSP (Python) error handling.
- A generic app-wide logging/telemetry pipeline — toasts and `console.error` are sufficient for this scope.
- Curated, hardcoded model recommendations independent of the dynamically fetched list.
- Retry/backoff logic for failed downloads or model-list fetches (out of scope; only surfacing the failure is in scope).
- Redesigning the model `<select>` into a richer picker component — the existing dropdown UI is kept, only its recommendation labeling changes.
