import { chromium, devices, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const outputDir = join(__dirname, '..', 'output', 'screenshots');
const baseURL = 'http://127.0.0.1:4173/modelable/playground/';

async function waitForReady(page) {
  await expect(page.locator('main.workbench')).not.toHaveAttribute('data-state', 'loading', {
    timeout: 90_000,
  });
}

async function captureDesktop(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  await page.goto(`${baseURL}?test=1&ai=heuristic`);
  await waitForReady(page);

  // Open the Assistant tab, send a chat message, and wait for the preview.
  await page.getByRole('tab', { name: 'Assistant' }).click();
  await page
    .getByPlaceholder('e.g. Add a creditScore field to Customer')
    .fill('an invoice');
  await page.getByRole('button', { name: 'Send' }).click();
  await page.getByText('AI generated source').waitFor({ timeout: 10_000 });
  await page.getByRole('button', { name: 'Accept' }).waitFor({ timeout: 10_000 });

  await page.screenshot({ path: join(outputDir, 'desktop-assistant.png'), fullPage: false });

  // Open the Output tab so the artifact list is visible.
  await page.getByRole('tab', { name: 'Output' }).click();
  // Generate artifacts for the current source.
  await page.getByRole('button', { name: 'Generate' }).click();
  await page.getByRole('button', { name: 'Download all' }).waitFor({ timeout: 10_000 });

  await page.screenshot({ path: join(outputDir, 'desktop-output.png'), fullPage: false });
  await context.close();
}

async function captureMobile(browser) {
  const context = await browser.newContext(devices['iPhone SE']);
  const page = await context.newPage();
  await page.goto(`${baseURL}?test=1&ai=heuristic`);
  await waitForReady(page);

  // Switch to the Assistant mobile view.
  await page.getByRole('button', { name: 'Assistant' }).click();
  await page
    .getByPlaceholder('e.g. Add a creditScore field to Customer')
    .fill('an invoice');
  await page.getByRole('button', { name: 'Send' }).click();
  const message = page.locator('.chat-message--assistant');
  await message.getByText('AI generated source').waitFor({ timeout: 10_000 });
  await message.getByRole('button', { name: 'Accept' }).waitFor({ timeout: 10_000 });
  await message.scrollIntoViewIfNeeded();

  await page.screenshot({ path: join(outputDir, 'mobile-assistant.png'), fullPage: false });
  await context.close();
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const browser = await chromium.launch();
  try {
    await captureDesktop(browser);
    await captureMobile(browser);
    console.log(`Screenshots saved to ${outputDir}`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
