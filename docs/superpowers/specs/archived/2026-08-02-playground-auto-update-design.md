# Playground service-worker auto-update

## Context

The Modelable playground is a Vite PWA. It currently uses `registerType: 'prompt'` and shows a manual “A new version is available” banner. Users can dismiss the banner and keep refreshing, which sometimes serves the old precached `index.html` and assets because the waiting service worker does not activate until all tabs are closed or the user explicitly clicks Reload.

## Goal

Ensure that a deployed update is applied as soon as it is ready, so a refresh never loads a stale cached version of the playground.

## Decision

Use Vite PWA’s built-in `autoUpdate` mode. This is the smallest, most reliable way to get the desired behavior.

## Design

1. **Vite config** (`web/vite.config.ts`)
   - Change VitePWA `registerType` from `'prompt'` to `'autoUpdate'`.
   - Leave the Workbox precache glob and scope unchanged.
   - With `autoUpdate`, Workbox will call `self.skipWaiting()` during install and `clients.claim()` during activate. The generated registration helper reloads the page once the new service worker takes control.

2. **Registration code** (`web/src/sw-registration.ts`)
   - Remove the update banner DOM manipulation and the `onNeedRefresh` callback.
   - Keep a thin `registerServiceWorker()` wrapper that calls `registerSW()` so registration stays explicit and testable.

3. **Tests** (`web/tests/service-worker.spec.ts`)
   - Remove the banner-dismiss test, because that UI no longer exists.
   - Keep the registration and offline tests.
   - Add a test that verifies the service worker controls the page after an update path (where feasible, by asserting `navigator.serviceWorker.controller` is set once the app is ready).

4. **Verification build**
   - Run `npm run build` in `web/` and inspect the generated `sw.js` to confirm it contains `skipWaiting` and `clientsClaim` instead of only listening for a `SKIP_WAITING` message.

## Safety

- Workspace state is already persisted to IndexedDB via `usePersistentWorkspace`, with a 300 ms debounce and a `pagehide` save of dirty state. An automatic reload should not lose work.
- The browser compiler client already disposes on `pagehide`, so it restarts cleanly after the reload.

## Out of scope

- Adding a user-visible “update pending” indicator. With `autoUpdate`, the page reloads automatically when the update activates.
- Server-side cache headers. GitHub Pages headers are outside the project’s control; the service worker is the update mechanism we are fixing.
