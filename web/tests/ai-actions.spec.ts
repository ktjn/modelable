import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { replaceSource, sourceOutput, waitForReady } from './helpers';

async function gotoWithHeuristic(page: Page): Promise<void> {
  await page.goto('?test=1&ai=heuristic');
  await waitForReady(page);
  await expect(
    page.getByPlaceholder('e.g. Add a creditScore field to Customer'),
  ).toBeVisible({ timeout: 5_000 });
}

test('activates heuristic AI and shows action buttons', async ({ page }) => {
  await gotoWithHeuristic(page);

  await expect(
    page.getByRole('button', { name: 'Explain workspace' }),
  ).toBeEnabled();
  await expect(
    page.getByRole('button', { name: 'Suggest projection' }),
  ).toBeEnabled();
  await expect(
    page.getByPlaceholder('e.g. Add a creditScore field to Customer'),
  ).toBeEnabled();
});

test('generate entity sends a chat message and shows preview', async ({
  page,
}) => {
  await gotoWithHeuristic(page);

  await page
    .getByPlaceholder('e.g. Add a creditScore field to Customer')
    .fill('an invoice');
  await page.getByRole('button', { name: 'Send' }).click();

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

test('explain shows AI explanation in chat', async ({ page }) => {
  await gotoWithHeuristic(page);

  await page.getByRole('button', { name: 'Explain workspace' }).click();
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
  await gotoWithHeuristic(page);

  await page
    .getByPlaceholder('e.g. Add a creditScore field to Customer')
    .fill('an invoice');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('AI generated source')).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole('button', { name: 'Accept' }).click();
  await expect(page.getByText('Accepted')).toBeVisible();
});

test('discard closes preview without modifying source', async ({ page }) => {
  await gotoWithHeuristic(page);

  const source =
    'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }';
  await replaceSource(page, source);

  await page.getByRole('button', { name: 'Explain workspace' }).click();
  await expect(page.getByText('AI explanation')).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole('button', { name: 'Close' }).click();
  await expect(page.getByText('Discarded')).toBeVisible();
  await expect(sourceOutput(page)).toContainText(/domain\s*customer/);
});

test('has no accessibility violations across the assistant panel', async ({
  page,
}) => {
  test.setTimeout(90_000);
  await gotoWithHeuristic(page);

  const panelResults = await new AxeBuilder({ page }).analyze();
  expect(panelResults.violations).toEqual([]);

  await page
    .getByPlaceholder('e.g. Add a creditScore field to Customer')
    .fill('an invoice');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('AI generated source')).toBeVisible({
    timeout: 10_000,
  });

  const previewResults = await new AxeBuilder({ page }).analyze();
  expect(previewResults.violations).toEqual([]);

  await page.getByRole('button', { name: 'Discard' }).click();
  await expect(page.getByText('Discarded')).toBeVisible();
});

test('no CSS animations are active with prefers-reduced-motion', async ({
  browser,
}) => {
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
