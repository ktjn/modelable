# 2026-07-23 Playground Offline and Hardening — Design

## Status

Proposed on 2026-07-23.

Execution will be broken into reviewable tasks in the
[Playground Offline and Hardening implementation plan](../plans/2026-07-23-playground-offline-hardening.md).

This specification defines Phase 7 of the
[Modelable Playground Architecture](../../playground-design.md). It builds on
the shipped browser compiler, editor, workspace persistence, language services,
visualization, analysis views, and local AI features to add offline operation
through a service worker, harden security and accessibility, optimize
performance, and validate cross-browser support.

## Context

The Playground is a fully static, browser-native IDE served from GitHub Pages.
All computation (parsing, validation, compilation, visualization, AI inference)
runs locally on the user's device. Despite this architecture, the application
currently requires a network connection for every page load because there is no
service worker to cache assets.

Key assets that must be fetched on every visit:

- The React application shell (HTML, CSS, JS, Monaco editor).
- The Pyodide WebAssembly runtime (~12 MB compressed).
- Python dependency wheels (lark, etc.).
- The Modelable browser wheel (~286 KB).
- WebLLM runtime (when AI features are used).

The application already has:

- A strict Content Security Policy (CSP) with `connect-src 'self'`.
- A local-request audit in all Playwright tests verifying no off-origin
  requests.
- An XSS protection test for hostile source input.
- SHA-256 verification of vendored Python assets at build time.
- Mature ARIA labeling, keyboard shortcuts, skip-link, and axe-core scans.
- Performance budgets enforced in CI (application ≤ 750 KB gzip, wheel ≤ 2 MB
  gzip, additional Python ≤ 15 MB gzip).
- Conformance-test latency budgets for compiler operations.
- Playwright e2e tests covering the editor workflow, AI actions, and
  conformance — currently Chromium only.

## Goals

- Cache all application assets in a service worker so the Playground starts
  offline after the first visit.
- Preserve unsaved workspace state across service worker updates.
- Add a Firefox Playwright test project to CI, extending cross-browser
  coverage.
- Enforce accessibility conformance in CI with a broader axe-core sweep
  covering AI action flows.
- Add a `prefers-reduced-motion` media query audit.
- Add an install prompt and minimal PWA manifest.
- Tighten performance budgets: enforce Monaco and AI worker chunk sizes.
- Add a long-task observer integration test to verify no main-thread task
  exceeds 100 ms during normal editing.
- Add subresource integrity (SRI) attributes to inline-critical assets where
  practical.

## Non-goals

- Ollama or remote BYOK provider integration (Phase 8).
- Plugin contracts or extension boundaries (Phase 8).
- Offline model caching for WebLLM (model assets are large and
  provider-managed; the service worker caches only the WebLLM runtime, not
  downloaded model weights).
- Background sync or push notifications.
- WebKit/Safari Playwright CI (Safari's WebAssembly and EditContext support
  requires manual verification for now).
- Visual regression screenshot tests (deferred to Phase 8).
- Modifying Modelable parsing, validation, formatting, compilation, registry,
  or compatibility semantics.

## Chosen approach

### Service worker

Use a build-time-generated service worker via
[vite-plugin-pwa](https://vite-pwa-org.netlify.app/) with Workbox precaching.
This avoids hand-rolling cache invalidation and integrates with the existing
Vite build pipeline.

Precache groups:

| Group             | Strategy     | Contents                                     |
|-------------------|--------------|----------------------------------------------|
| Application shell | Precache     | HTML, CSS, JS, Monaco chunk, AI worker chunk |
| Pyodide runtime   | Precache     | `pyodide.asm.wasm`, `pyodide.mjs`, `python_stdlib.zip`, `pyodide-lock.json` |
| Python wheels     | Precache     | Modelable browser wheel, lark wheel, dependency wheels |
| Fonts and images  | Precache     | Codicon font (data URI), favicon              |
| Fixtures          | Runtime only | Conformance test fixtures (dev only, not precached) |

All precached assets are content-hashed at build time. The service worker uses
Workbox's revision hash for assets that lack a hash in their filename (e.g.,
`index.html`).

#### Update flow

When a new version is deployed:

1. The service worker detects updated precache entries on the next visit.
2. New assets are downloaded in the background.
3. The UI displays a non-blocking "Update available" banner.
4. The user can dismiss the banner or click "Reload" to activate the new
   version.
5. The service worker activates only after the user confirms or on the next
   cold navigation. It never force-activates while unsaved workspace state
   exists.

The update banner is a lightweight `<div>` outside React's root to avoid
coupling service worker lifecycle to React state. It communicates with the
service worker via `postMessage`.

#### CSP adjustment

The current CSP does not require changes. The service worker is same-origin
(`worker-src 'self'`) and all cached responses are same-origin
(`connect-src 'self'`). `vite-plugin-pwa` generates a same-origin service
worker script that Vite includes in the build output.

#### Scope

The service worker scope is `/modelable/playground/` matching the Vite base
path. This ensures it only intercepts requests for the Playground, not the
MkDocs documentation or other GitHub Pages content.

### PWA manifest

Add a minimal `manifest.json`:

```json
{
  "name": "Modelable Playground",
  "short_name": "Modelable",
  "start_url": "/modelable/playground/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#1a1a2e",
  "icons": [
    { "src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

Icons will be simple geometric Modelable logos generated as static assets.
The manifest enables the browser install prompt ("Add to Home Screen") on
supporting platforms.

### Cross-browser validation

Add a Firefox Playwright project to `web/playwright.config.ts`:

```ts
projects: [
  {
    name: 'chromium',
    use: { ...devices['Desktop Chrome'] },
  },
  {
    name: 'firefox',
    use: { ...devices['Desktop Firefox'] },
  },
],
```

Known Firefox differences to handle:

- **EditContext API**: Firefox does not support EditContext. The existing
  textarea fallback path already handles this. The Playwright test
  `playground.spec.ts` already tests the EditContext-unavailable scenario
  (line 511), so this path is exercised by default in Firefox.
- **WebGPU**: Firefox Nightly has WebGPU behind a flag, but stable Firefox does
  not. AI tests that require WebGPU are skipped in Firefox; heuristic AI tests
  run in all browsers.
- **IndexedDB**: Firefox's IndexedDB implementation is compatible; no changes
  needed.

The Firefox project runs the same test suite. Tests that depend on
Chromium-specific APIs use `test.skip` with a browser-name check.

### Accessibility hardening

#### Expanded axe-core coverage

Add axe-core scans to the AI action test suite (`ai-actions.spec.ts`). Run a
scan after:

1. The AI toolbar is visible with action buttons.
2. The prompt dialog is open.
3. The preview panel is showing generated source.

This ensures the new AI UI meets automated accessibility standards.

#### Reduced motion

Add a `prefers-reduced-motion` media query to `web/src/style.css` that
disables:

- CSS transitions on panel open/close.
- Any future animation on the download progress bar.

Add a Playwright test that emulates `prefers-reduced-motion: reduce` and
verifies no CSS animations are active.

#### Focus management audit

Verify in Playwright tests that:

- Focus moves to the prompt input when the Generate Entity dialog opens.
- Focus returns to the triggering button when the dialog closes.
- Focus moves to the preview panel when AI generation completes.
- Focus returns to the source editor when the preview is accepted or
  discarded.

### Performance hardening

#### Enforce chunk budgets

Promote the `monaco` and `aiWorker` report-only categories in
`check-budgets.mjs` to enforced budgets:

| Category    | Budget (gzip) |
|-------------|---------------|
| `monaco`    | 1.5 MB        |
| `aiWorker`  | 500 KB        |

#### Long-task observer test

Add a Playwright integration test that:

1. Navigates to the playground and waits for the compiler to be ready.
2. Installs a `PerformanceObserver` for `longtask` entries.
3. Performs a sequence of normal editing operations (type source, validate,
   format).
4. Asserts no `longtask` entry exceeds 100 ms.

This enforces the architecture document's performance target (section 17):
"No main-thread task above 100 ms during normal editing."

#### Lazy-load AI components

The AI preview panel and prompt dialog are only needed when the user triggers
an AI action. Wrap them in `React.lazy()` to keep them out of the initial
bundle, matching the existing pattern used by `AnalysisPanelContainer` and
`GraphPanelContainer`.

### Security hardening

#### Subresource integrity

The application entry point (`<script type="module" src="/src/main.tsx">`) is
same-origin and does not benefit from SRI in production (Vite inlines it into
the built `index.html` with a content-hashed filename). SRI is most valuable
for CDN-hosted third-party scripts, which the Playground does not use.

No SRI changes are needed. The existing CSP (`script-src 'self'`) already
restricts script execution to same-origin.

#### Service worker security

The service worker introduces a new trust boundary. Mitigations:

- The service worker only caches same-origin responses. Cross-origin requests
  (if any are ever permitted by CSP changes) fall through to the network.
- The Workbox precache manifest is generated at build time with content hashes,
  preventing cache poisoning.
- The service worker scope is restricted to `/modelable/playground/`.

#### Local request audit extension

Extend the existing local-request audit to also run during service worker
registration and update checks, verifying that the service worker itself does
not make off-origin requests.

## Architecture decision scope

No new ADR is required. The service worker, PWA manifest, Firefox testing,
accessibility hardening, and performance enforcement all implement existing
architecture document guidance (sections 15, 16, 17, 18, 19) without
introducing new architectural boundaries.

The `playground-design.md` status line should be updated to reflect Phase 7 as
the active phase.
