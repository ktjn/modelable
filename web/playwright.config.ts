import { defineConfig, devices } from '@playwright/test';

const project = process.env.PLAYWRIGHT_PROJECT;
export const playwrightBaseURL = 'http://127.0.0.1:4173/modelable/playground/';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  workers: '50%',
  // Retries are CI-only: locally, a failure should surface immediately
  // rather than be masked by a silent retry. In CI, a test that fails once
  // and then passes is reported as "flaky" (not "passed") by the JSON
  // reporter -- report-flaky-tests.mjs surfaces those without failing the
  // build, so intermittent tests stay visible instead of being silently
  // absorbed.
  retries: process.env.CI ? 2 : 0,
  timeout: 60_000,
  globalTimeout: 30 * 60_000,
  reporter: [
    ['list'],
    ['json', { outputFile: 'output/playwright/results.json' }],
  ],
  outputDir: 'output/playwright',
  use: {
    baseURL: playwrightBaseURL,
    trace: 'retain-on-failure',
  },
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.02,
    },
  },
  projects: [
    ...(project === undefined || project === 'chromium'
      ? [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
      : []),
  ],
  webServer: {
    command: 'npm run preview',
    port: 4173,
    reuseExistingServer: !!process.env.CI,
  },
});
