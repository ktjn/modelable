import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium, devices, test as base } from '@playwright/test';
import type { BrowserContext, Page } from '@playwright/test';

const here = path.dirname(fileURLToPath(import.meta.url));

/**
 * Persisted on disk under `web/output/` (already gitignored) instead of a
 * throwaway per-run context, so the WebLLM model weights this suite
 * downloads into Cache Storage / IndexedDB survive between runs. Without
 * this, every `npm run test:e2e:manual` invocation would re-download every
 * model under test from scratch.
 *
 * Delete this directory to force a clean re-download (e.g. after bumping
 * `@mlc-ai/web-llm` or changing the curated model list).
 */
const PROFILE_DIR = path.resolve(here, '../output/webllm-profile');

export const test = base.extend<{ context: BrowserContext; page: Page }>({
  // eslint-disable-next-line no-empty-pattern
  context: async ({}, use, testInfo) => {
    const context = await chromium.launchPersistentContext(PROFILE_DIR, {
      ...devices['Desktop Chrome'],
      headless: process.env.PLAYWRIGHT_HEADLESS === '1',
      baseURL: 'http://127.0.0.1:4173/modelable/playground/',
    });
    await context.tracing.start({ screenshots: true, snapshots: true });

    await use(context);

    const keepTrace = testInfo.status !== testInfo.expectedStatus;
    await context.tracing.stop(
      keepTrace ? { path: testInfo.outputPath('trace.zip') } : undefined,
    );
    await context.close();
  },
  page: async ({ context }, use) => {
    const page = context.pages()[0] ?? (await context.newPage());
    await use(page);
  },
});

export { expect } from '@playwright/test';
