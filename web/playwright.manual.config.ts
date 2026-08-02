import { defineConfig } from '@playwright/test';

/**
 * Opt-in config for tests that exercise the playground against a real
 * WebLLM model over WebGPU instead of the deterministic `?ai=simulator`
 * provider. These tests download real model weights from Hugging Face /
 * GitHub and need genuine WebGPU compute, so they are never run by
 * `npm run test:e2e` or CI (see `playwright.config.ts`).
 *
 * Usage (from `web/`):
 *   npm run build
 *   npm run test:e2e:manual
 *
 * Tests in `tests-manual/` import `test`/`expect` from `./fixtures`, not
 * `@playwright/test` directly — that fixture launches a persistent browser
 * context (so downloaded model weights survive between runs) and owns
 * baseURL/headless/tracing itself. The `use` block below is intentionally
 * minimal; per-context options belong in `fixtures.ts`.
 */
export default defineConfig({
  testDir: './tests-manual',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // Model download, WASM compile, and first-token latency vary a lot by
  // hardware and network; give individual tests generous headroom instead
  // of guessing.
  timeout: 10 * 60_000,
  globalTimeout: 60 * 60_000,
  reporter: [['list']],
  outputDir: 'output/playwright-manual',
  webServer: {
    command: 'npm run preview',
    port: 4173,
    reuseExistingServer: true,
  },
});
