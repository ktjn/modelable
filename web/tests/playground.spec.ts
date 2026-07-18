import { expect, test } from '@playwright/test';

const validCompact =
  'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid displayName?: string } }';

test('initializes locally and supports the complete proof workflow', async ({ page }) => {
  const networkRequests: string[] = [];
  page.on('request', (request) => {
    const url = request.url();
    if (url.startsWith('http://') || url.startsWith('https://')) {
      networkRequests.push(url);
    }
  });

  await page.goto('?test=1', { waitUntil: 'domcontentloaded' });
  const actions = [
    page.getByRole('button', { name: 'Validate' }),
    page.getByRole('button', { name: 'Format' }),
    page.getByRole('button', { name: 'Generate JSON Schema' }),
  ];
  await expect(page.getByRole('status')).toHaveText(/initializing compiler/i);
  for (const action of actions) {
    await expect(action).toBeDisabled();
  }
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });
  await expect(page.getByLabel('Model source')).toHaveValue(/entity Customer/);

  await page.getByLabel('Model source').fill(validCompact);
  await actions[0].click();
  await expect(actions[1]).toBeDisabled();
  await expect(page.getByTestId('diagnostics')).toContainText('No diagnostics');

  await actions[1].click();
  await expect(page.getByLabel('Model source')).toHaveValue(/domain customer \{\n/);

  await actions[2].click();
  await expect(page.getByTestId('artifacts')).toContainText('"title": "Customer"');
  await expect(page.getByTestId('metrics')).toContainText(/initialization\s+\d+\.\d ms/i);
  await expect(page.getByTestId('metrics')).toContainText(/operation\s+\d+\.\d ms/i);

  expect(
    networkRequests.every(
      (url) => new URL(url).origin === 'http://127.0.0.1:4173',
    ),
  ).toBe(true);
});

test('keeps keyboard order clear and treats hostile-looking source as text', async ({
  page,
}) => {
  await page.goto('?test=1');
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });

  await page.getByRole('link', { name: 'Skip to source' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Model source')).toBeFocused();
  for (const label of ['Validate', 'Format', 'Generate JSON Schema']) {
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: label })).toBeFocused();
  }

  const hostileSource = [
    'globalThis.__modelablePwned = true;',
    '__import__("os").system("echo no")',
    '<img src=x onerror="globalThis.__modelablePwned=true">',
  ].join('\n');
  await page.getByLabel('Model source').fill(hostileSource);
  await page.getByRole('button', { name: 'Validate' }).click();

  await expect(page.getByTestId('diagnostics')).toContainText('PARSE');
  expect(
    await page.evaluate(
      () =>
        '__modelablePwned' in
        (globalThis as typeof globalThis & {
          __modelablePwned?: boolean;
        }),
    ),
  ).toBe(false);
  await expect(page.locator('img')).toHaveCount(0);
});

test('does not expose the compiler client without explicit test opt-in', async ({
  page,
}) => {
  await page.goto('');
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });

  expect(
    await page.evaluate(
      () => '__modelableBrowserCompiler' in globalThis,
    ),
  ).toBe(false);
});
