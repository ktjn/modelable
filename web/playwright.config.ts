import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  globalTimeout: 25 * 60_000,
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
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
  ],
  webServer: {
    command: 'npm run preview',
    port: 4173,
    reuseExistingServer: false,
  },
});
