import AxeBuilder from '@axe-core/playwright';
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

async function gotoWithHeuristic(page: Page): Promise<void> {
  await page.goto('?test=1&ai=heuristic');
  await waitForReady(page);
  await expect(
    page.getByRole('button', { name: 'Generate entity' }),
  ).toBeVisible({ timeout: 5_000 });
}

test('activates heuristic AI and shows action buttons', async ({ page }) => {
  test.setTimeout(60_000);
  await gotoWithHeuristic(page);

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
  await gotoWithHeuristic(page);

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
  await gotoWithHeuristic(page);

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
  await gotoWithHeuristic(page);

  await page.getByRole('button', { name: 'Suggest projection' }).click();
  await expect(page.getByText('AI generated source')).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole('button', { name: 'Accept' }).click();
  await expect(page.getByText('AI generated source')).toBeHidden();
});

test('discard closes preview without modifying source', async ({ page }) => {
  test.setTimeout(60_000);
  await gotoWithHeuristic(page);

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
  await gotoWithHeuristic(page);

  await page.getByRole('button', { name: 'Generate entity' }).click();
  const dialog = page.getByRole('dialog', { name: 'Generate entity' });
  await expect(dialog).toBeVisible();

  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText('AI generated source')).toBeHidden();
});

test('prompt dialog cancels with Escape key', async ({ page }) => {
  test.setTimeout(60_000);
  await gotoWithHeuristic(page);

  await page.getByRole('button', { name: 'Generate entity' }).click();
  const dialog = page.getByRole('dialog', { name: 'Generate entity' });
  await expect(dialog).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('has no accessibility violations with AI toolbar visible', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await gotoWithHeuristic(page);

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test('has no accessibility violations with prompt dialog open', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await gotoWithHeuristic(page);

  await page.getByRole('button', { name: 'Generate entity' }).click();
  await expect(
    page.getByRole('dialog', { name: 'Generate entity' }),
  ).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test('has no accessibility violations with AI preview visible', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await gotoWithHeuristic(page);

  await page.getByRole('button', { name: 'Explain' }).click();
  await expect(page.getByText('AI explanation')).toBeVisible({
    timeout: 10_000,
  });

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test('focus moves to prompt input on dialog open and returns on close', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await gotoWithHeuristic(page);

  const generateButton = page.getByRole('button', {
    name: 'Generate entity',
  });
  await generateButton.click();
  const dialog = page.getByRole('dialog', { name: 'Generate entity' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('textbox')).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('focus moves to preview on generation and returns on discard', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await gotoWithHeuristic(page);

  await page.getByRole('button', { name: 'Suggest projection' }).click();
  const preview = page.getByText('AI generated source');
  await expect(preview).toBeVisible({ timeout: 10_000 });

  await page.getByRole('button', { name: 'Discard' }).click();
  await expect(preview).toBeHidden();
});

test('no CSS animations are active with prefers-reduced-motion', async ({
  browser,
}) => {
  test.setTimeout(60_000);
  const context = await browser.newContext({
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  try {
    await page.goto('?test=1&ai=heuristic');
    await waitForReady(page);

    const animations = await page.evaluate(() => {
      const active: { element: string; duration: string }[] = [];
      for (const el of document.querySelectorAll('*')) {
        const style = getComputedStyle(el);
        const animDuration = parseFloat(style.animationDuration);
        const transDuration = parseFloat(style.transitionDuration);
        if (animDuration > 0.02) {
          active.push({
            element: el.tagName + (el.className ? `.${el.className}` : ''),
            duration: style.animationDuration,
          });
        }
        if (transDuration > 0.02) {
          active.push({
            element: el.tagName + (el.className ? `.${el.className}` : ''),
            duration: style.transitionDuration,
          });
        }
      }
      return active;
    });
    expect(animations).toEqual([]);
  } finally {
    await context.close();
  }
});

test('no main-thread task exceeds 100ms during standard editing', async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto('?test=1');
  await waitForReady(page);

  const longTasks = await page.evaluate(async () => {
    const tasks: { duration: number; name: string }[] = [];
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        tasks.push({ duration: entry.duration, name: entry.name });
      }
    });
    observer.observe({ type: 'longtask', buffered: false });

    const editor = document.querySelector(
      '.source-editor .view-lines',
    ) as HTMLElement | null;
    editor?.click();
    const input = document.querySelector(
      '[aria-label^="Model source"]',
    ) as HTMLElement | null;
    input?.focus();

    for (const char of 'domain test { owner: "team" }') {
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: char, bubbles: true }),
      );
      await new Promise((r) => setTimeout(r, 20));
    }

    const validateButton = Array.from(
      document.querySelectorAll('button'),
    ).find((b) => b.textContent?.includes('Validate'));
    validateButton?.click();
    await new Promise((r) => setTimeout(r, 500));

    const formatButton = Array.from(
      document.querySelectorAll('button'),
    ).find((b) => b.textContent?.includes('Format'));
    formatButton?.click();
    await new Promise((r) => setTimeout(r, 500));

    observer.disconnect();
    return tasks;
  });

  for (const task of longTasks) {
    expect(task.duration).toBeLessThanOrEqual(100);
  }
});
