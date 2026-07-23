import { expect, test, type Page } from '@playwright/test';

function modelSource(page: Page) {
  return page.getByRole('textbox', { name: 'Model source' });
}

function sourceOutput(page: Page) {
  return page.locator('.source-editor .view-lines');
}

async function waitForReady(page: Page): Promise<void> {
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });
}

async function focusSourceEditor(page: Page): Promise<void> {
  await sourceOutput(page).click({
    position: { x: 8, y: 8 },
    force: true,
  });
  await modelSource(page).focus();
  await expect(modelSource(page)).toBeFocused();
}

async function replaceSource(page: Page, text: string): Promise<void> {
  await focusSourceEditor(page);
  await page.keyboard.press('Control+a');
  await page.keyboard.press('Backspace');
  await expect(sourceOutput(page)).toHaveText('');
  await page.keyboard.type(text);
}

async function activateHeuristicProvider(page: Page): Promise<void> {
  await page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, 'gpu', {
      configurable: true,
      get() {
        return undefined;
      },
    });
  });
  await page.goto('?test=1');
  await waitForReady(page);
  await page.getByRole('button', { name: 'Use heuristic AI' }).click();
  await expect(
    page.getByRole('button', { name: 'Generate entity' }),
  ).toBeVisible({ timeout: 5_000 });
}

test('activates heuristic AI and shows action buttons', async ({ page }) => {
  test.setTimeout(60_000);
  await activateHeuristicProvider(page);

  await expect(
    page.getByRole('button', { name: 'Generate entity' }),
  ).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Explain' })).toBeEnabled();
  await expect(
    page.getByRole('button', { name: 'Suggest projection' }),
  ).toBeEnabled();
});

test('generate entity opens prompt, submits, and shows preview', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await activateHeuristicProvider(page);

  await page.getByRole('button', { name: 'Generate entity' }).click();
  const dialog = page.getByRole('dialog', { name: 'Generate entity' });
  await expect(dialog).toBeVisible();

  await dialog.getByRole('textbox').fill('an invoice');
  await dialog.getByRole('button', { name: 'Generate' }).click();
  await expect(dialog).toBeHidden();

  await expect(page.getByText('AI generated source')).toBeVisible({
    timeout: 10_000,
  });
  await expect(
    page.getByRole('button', { name: 'Accept' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Discard' }),
  ).toBeVisible();
  await expect(page.getByText('heuristic / heuristic')).toBeVisible();
});

test('explain shows AI explanation preview', async ({ page }) => {
  test.setTimeout(60_000);
  await activateHeuristicProvider(page);

  await page.getByRole('button', { name: 'Explain' }).click();
  await expect(page.getByText('AI explanation')).toBeVisible({
    timeout: 10_000,
  });
  await expect(
    page.getByRole('button', { name: 'Close' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Accept' }),
  ).toHaveCount(0);
});

test('accept applies generated source to the editor', async ({ page }) => {
  test.setTimeout(60_000);
  await activateHeuristicProvider(page);

  await page.getByRole('button', { name: 'Suggest projection' }).click();
  await expect(page.getByText('AI generated source')).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole('button', { name: 'Accept' }).click();
  await expect(page.getByText('AI generated source')).toBeHidden();
});

test('discard closes preview without modifying source', async ({ page }) => {
  test.setTimeout(60_000);
  await activateHeuristicProvider(page);

  const source =
    'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }';
  await replaceSource(page, source);

  await page.getByRole('button', { name: 'Explain' }).click();
  await expect(page.getByText('AI explanation')).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole('button', { name: 'Close' }).click();
  await expect(page.getByText('AI explanation')).toBeHidden();
  await expect(sourceOutput(page)).toContainText(/domain\s+customer/);
});

test('prompt dialog cancels with Cancel button', async ({ page }) => {
  test.setTimeout(60_000);
  await activateHeuristicProvider(page);

  await page.getByRole('button', { name: 'Generate entity' }).click();
  const dialog = page.getByRole('dialog', { name: 'Generate entity' });
  await expect(dialog).toBeVisible();

  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText('AI generated source')).toBeHidden();
});

test('prompt dialog cancels with Escape key', async ({ page }) => {
  test.setTimeout(60_000);
  await activateHeuristicProvider(page);

  await page.getByRole('button', { name: 'Generate entity' }).click();
  const dialog = page.getByRole('dialog', { name: 'Generate entity' });
  await expect(dialog).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});
