import { defineConfig, devices } from '@playwright/test';

const project = process.env.PLAYWRIGHT_PROJECT;

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  workers: process.env.CI ? (project === 'firefox' ? 1 : 2) : '50%',
  retries: 0,
  timeout: 60_000,
  globalTimeout: 30 * 60_000,
  reporter: [
    ['list'],
    ['json', { outputFile: 'output/playwright/results.json' }],
  ],
  outputDir: 'output/playwright',
  use: {
    baseURL: 'http://127.0.0.1:4173/modelable/playground/',
    trace: 'retain-on-failure',
  },
  projects: [
    ...(project === undefined || project === 'chromium'
      ? [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
      : []),
    ...(project === undefined || project === 'firefox'
      ? [{ name: 'firefox', use: { ...devices['Desktop Firefox'] } }]
      : []),
  ],
  webServer: {
    command: 'npm run preview',
    port: 4173,
    reuseExistingServer: !!process.env.CI,
  },
});
