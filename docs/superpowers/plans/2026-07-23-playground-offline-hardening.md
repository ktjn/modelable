# 2026-07-23 Playground Offline and Hardening — Plan

## Status

Proposed on 2026-07-23. Implements the
[Playground Offline and Hardening design](../specs/2026-07-23-playground-offline-hardening-design.md).

## Batch order

Work is split into four batches. Each batch is a single reviewable PR.

### Batch A — Service worker and PWA manifest

1. Add `vite-plugin-pwa` dependency in `web/package.json`.
2. Configure the plugin in `web/vite.config.ts` with Workbox precaching for
   application shell, Pyodide runtime, Python wheels, and static assets.
   Scope the service worker to `/modelable/playground/`.
3. Add PWA icon assets (`web/public/icons/icon-192.png`,
   `web/public/icons/icon-512.png`) as simple geometric logos.
4. Add `manifest.json` generation through the plugin configuration (name,
   short name, start URL, display mode, colors, icons).
5. Add a non-React update banner (`web/src/sw-update-banner.ts`) that
   listens for service worker `controllerchange` events, displays
   "Update available — Reload", and posts `SKIP_WAITING` to the new service
   worker on user confirmation.
6. Integrate the update banner in `web/src/main.tsx` by calling the
   registration hook after React mounts.
7. Add a Playwright e2e test that verifies the service worker registers,
   caches assets, and serves the application shell from cache on a second
   navigation with the network disabled.
8. Add a Playwright test that verifies the update banner appears when a
   simulated service worker update is detected.
9. Verify the existing CSP, local-request audit, and XSS tests still pass
   with the service worker active.

### Batch B — Cross-browser validation

1. Add the Firefox Playwright project to `web/playwright.config.ts`.
2. Add browser-specific `test.skip` guards for tests that require
   Chromium-specific APIs (EditContext creation, WebGPU-dependent AI tests).
3. Run the full Playwright suite against Firefox locally and fix any
   Firefox-specific failures (expected: textarea fallback path, IndexedDB
   minor differences).
4. Update the CI workflow (`.github/workflows/validate.yml`) to install
   Firefox in the browser playground job and run both Chromium and Firefox
   projects.
5. Verify all existing conformance, performance, and accessibility tests pass
   in both browsers.

### Batch C — Accessibility and performance hardening

1. Add axe-core scans to `web/tests/ai-actions.spec.ts` covering the AI
   toolbar, prompt dialog, and preview panel states.
2. Add `prefers-reduced-motion: reduce` CSS rules in `web/src/style.css`
   disabling transitions and animations.
3. Add a Playwright test that emulates `prefers-reduced-motion: reduce` and
   verifies no CSS animations are active on the page.
4. Add focus-management Playwright assertions: focus moves to prompt input on
   dialog open, returns to trigger button on close, moves to preview on
   generation, returns to editor on accept/discard.
5. Add a long-task observer Playwright test that verifies no main-thread task
   exceeds 100 ms during a standard editing sequence (type, validate, format).
6. Promote `monaco` (1.5 MB) and `aiWorker` (500 KB) to enforced budgets in
   `web/scripts/check-budgets.mjs`.
7. Wrap `AiPreviewPanel` and the prompt dialog in `React.lazy()` to reduce
   initial bundle size.
8. Verify all budgets pass after the lazy-loading change.

### Batch D — Closeout and documentation

1. Update the `playground-design.md` status line to mark Phase 7 as shipped
   and Phase 8 as the active next phase.
2. Archive the Phase 7 spec and plan to the `archived/` directories.
3. Verify all CI gates pass on the final state.

## Verification

Each batch must pass:

- `npm run typecheck` — no type errors.
- `npm run test` — all unit tests pass.
- `npm run lint` — no lint violations.
- `npx playwright test` — all e2e tests pass (Chromium; Firefox from Batch B).
- `npm run check:budgets` — all enforced budgets met.
- No new accessibility violations in axe-core checks.
- Existing performance budgets maintained.
