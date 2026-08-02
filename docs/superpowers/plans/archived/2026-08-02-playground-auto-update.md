# Playground service-worker auto-update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch the playground PWA to Vite PWA’s `autoUpdate` mode so deployed updates apply automatically and refreshes never serve a stale cached version.

**Architecture:** Change one VitePWA config flag, replace the manual update banner with a minimal `registerSW()` call, and update the service-worker e2e tests to match the new behavior. Verify the generated service worker contains `skipWaiting`/`clientsClaim`.

**Tech Stack:** Vite 8, vite-plugin-pwa, Workbox, Playwright, TypeScript/React.

## Global Constraints

- Keep the service worker scope `/modelable/playground/` and precache glob patterns unchanged.
- Workspace state is persisted to IndexedDB; do not add new persistence code.
- Remove the `onNeedRefresh` banner DOM code entirely.
- All existing service-worker registration and offline behavior must still work.

---

### Task 1: Switch VitePWA to autoUpdate mode

**Files:**
- Modify: `web/vite.config.ts:13`

**Interfaces:**
- Consumes: none
- Produces: VitePWA `registerType: 'autoUpdate'`

- [ ] **Step 1: Change registerType**

Replace `registerType: 'prompt',` with `registerType: 'autoUpdate',` in `web/vite.config.ts`.

```ts
VitePWA({
  registerType: 'autoUpdate',
  scope: '/modelable/playground/',
  ...
})
```

- [ ] **Step 2: Run TypeScript check**

Run:
```bash
cd web
npm run check
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/vite.config.ts
git commit -m "feat(web): use autoUpdate service worker mode"
```

---

### Task 2: Replace manual banner registration with minimal registration

**Files:**
- Modify: `web/src/sw-registration.ts`

**Interfaces:**
- Consumes: `registerSW` from `virtual:pwa-register`
- Produces: `registerServiceWorker()` exported function (signature unchanged)

- [ ] **Step 1: Replace the entire module content**

Replace the contents of `web/src/sw-registration.ts` with:

```ts
export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) {
    return;
  }
  window.addEventListener('load', () => {
    void import('virtual:pwa-register').then(({ registerSW }) => {
      registerSW();
    });
  });
}
```

This removes the `onNeedRefresh` callback and the `showUpdateBanner` helper because `autoUpdate` handles the reload automatically.

- [ ] **Step 2: Run unit tests**

Run:
```bash
cd web
npm run test
```
Expected: all existing unit tests pass.

- [ ] **Step 3: Commit**

```bash
git add web/src/sw-registration.ts
git commit -m "refactor(web): remove manual PWA update banner"
```

---

### Task 3: Update service-worker e2e tests

**Files:**
- Modify: `web/tests/service-worker.spec.ts`

**Interfaces:**
- Consumes: `waitForReady` helper
- Produces: updated Playwright tests

- [ ] **Step 1: Remove the banner-dismiss test**

Delete the test block starting at line 46:

```ts
test('update banner appears and can be dismissed', async ({ page }) => {
  ...
});
```

- [ ] **Step 2: Add a controller assertion**

Add a new test after the offline test to confirm the service worker controls the page:

```ts
test('service worker controls the page after load', async ({ page }) => {
  await page.goto('?test=1');
  await waitForReady(page);

  const controllerUrl = await page.evaluate(() =>
    navigator.serviceWorker.controller?.scriptURL,
  );
  expect(controllerUrl).toContain('/modelable/playground/sw.js');
});
```

- [ ] **Step 3: Run service-worker e2e tests**

Run:
```bash
cd web
npm run test:e2e -- tests/service-worker.spec.ts
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add web/tests/service-worker.spec.ts
git commit -m "test(web): remove update banner test and assert SW controller"
```

---

### Task 4: Verify generated service worker

**Files:**
- Generated: `web/dist/sw.js`

**Interfaces:**
- Consumes: VitePWA build output
- Produces: confidence that autoUpdate generated the expected service worker

- [ ] **Step 1: Build the playground**

Run:
```bash
cd web
npm run build
```
Expected: build completes without errors.

- [ ] **Step 2: Inspect the generated service worker**

Run:
```bash
grep -oE 'skipWaiting|clients\.claim' web/dist/sw.js | sort -u
```
Expected: output contains both `skipWaiting` and `clients.claim`.

- [ ] **Step 3: Ensure no manual SKIP_WAITING listener remains**

Run:
```bash
grep -c 'SKIP_WAITING' web/dist/sw.js || true
```
Expected: count is `0`. If it is not, VitePWA is still generating the prompt-mode service worker.

- [ ] **Step 4: Commit (if build artifacts are tracked)**

Only if `web/dist` is tracked in this repo:
```bash
git add web/dist
git commit -m "chore(web): rebuild service worker in autoUpdate mode"
```
If `web/dist` is ignored, skip this commit.

---

### Task 5: Full verification

**Files:**
- none (verification only)

- [ ] **Step 1: Run all web checks**

Run:
```bash
cd web
npm run check
npm run test
npm run test:e2e
```
Expected: all pass.

- [ ] **Step 2: Final commit if any remaining changes**

```bash
git status
# commit anything left
```

---

## Self-Review

- [ ] Spec coverage: every design section maps to a task.
- [ ] Placeholder scan: no TBD, TODO, or "fill in later" items.
- [ ] Type consistency: `registerServiceWorker()` keeps the same no-arg, void-return signature; test helper usage matches existing tests.
