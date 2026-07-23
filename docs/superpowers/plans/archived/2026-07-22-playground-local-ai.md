# 2026-07-22 Playground Local AI — Plan

## Status

Shipped on 2026-07-22. Implements the
[Playground Local AI design](../specs/2026-07-22-playground-local-ai-design.md).

## Batch order

Work is split into three batches. Each batch is a single reviewable PR.

### Batch A — AI protocol, Python bridge, and heuristic provider

1. Add `LlmRequest`, `LlmResponse`, and `LlmProvider` TypeScript types in
   `web/src/ai/types.ts`.
2. Add the `HeuristicProvider` in `web/src/ai/heuristic-provider.ts` that
   returns deterministic scaffolds for entity generation and compiler-rendered
   explanations without model download.
3. Add `BrowserLlmRequest`, `BrowserAiGenerateResult`, and
   `BrowserAiExplainResult` DTOs in `cli/src/modelable/browser/dto.py`.
4. Add `cli/src/modelable/browser/ai.py` with prompt builders and result
   parsers for generate-entity, explain, and suggest-projection.
5. Extend `cli/src/modelable/browser/dispatch.py` with `ai.generate` and
   `ai.explain` methods using two-phase pending/complete dispatch.
6. Extend `web/src/protocol.ts` with `ai.generate` and `ai.explain` method
   types, pending-LLM response type, and result type guards.
7. Extend `web/src/client.ts` with `aiGenerate` and `aiExplain` methods that
   handle the two-phase dispatch (send request → receive pending → invoke
   provider → re-dispatch with response).
8. Add unit tests for the heuristic provider, protocol types, and client
   methods.
9. Add Python tests for the browser AI module and dispatch extensions.

### Batch B — WebLLM worker and provider UI

1. Add `@mlc-ai/web-llm` dependency in `web/package.json`.
2. Add `web/src/ai/ai.worker.ts` Web Worker that loads WebLLM, handles
   `initialize`, `complete`, and `dispose` messages with progress reporting.
3. Add `web/src/ai/webgpu-provider.ts` implementing `LlmProvider` using the
   AI worker with WebGPU capability detection.
4. Add `web/src/ai/provider-state.ts` with provider state management
   (`idle | detecting | downloading | ready | error | unsupported`).
5. Add AI toolbar section in `web/src/App.tsx`: provider status indicator,
   model download button with progress bar.
6. Add CSS styles for the AI toolbar section in `web/src/style.css`.
7. Add unit tests for the WebGPU provider, AI worker protocol, and provider
   state management.

### Batch C — AI actions, preview panel, and e2e tests

1. Add AI action buttons in the source editor toolbar: Generate Entity,
   Explain, Suggest Projection.
2. Add prompt input dialog for Generate Entity action.
3. Add `web/src/ai/AiPreviewPanel.tsx` showing proposed source, diff,
   diagnostics, accept/discard buttons.
4. Wire AI actions through the client to the compiler worker, handle the
   two-phase dispatch, and render results in the preview panel.
5. Add provenance recording on accept (provider, model, timestamp stored in
   workspace metadata).
6. Add unit tests for AI action components and preview panel.
7. Add Playwright e2e tests for AI actions using the heuristic provider
   (no WebGPU required in CI).
8. Verify all existing conformance, performance, and accessibility gates pass.

## Verification

Each batch must pass:

- `npm run typecheck` — no type errors.
- `npm run test` — all unit tests pass.
- `npm run lint` — no lint violations.
- `npx playwright test` — all e2e tests pass.
- No new accessibility violations in axe-core checks.
- Existing performance budgets maintained.
