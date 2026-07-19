import AxeBuilder from '@axe-core/playwright';
import {
  expect,
  test,
  type BrowserContext,
  type Page,
  type Request,
} from '@playwright/test';

const validCompact =
  'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid displayName?: string } }';
const invalidSource = 'this is not valid Modelable source';
const importedSource =
  'domain imported { owner: "team" entity Imported @ 1 (additive) { @key importedId: uuid } }';
const runtimeManifest = '**/python/runtime-manifest.json';
const localOrigin = 'http://127.0.0.1:4173';
const localRequestAudits = new WeakMap<BrowserContext, () => void>();

function startLocalRequestAudit(context: BrowserContext): () => void {
  const offOriginRequests: string[] = [];
  const handleRequest = (request: Request): void => {
    const url = new URL(request.url());
    if (
      (url.protocol === 'http:' || url.protocol === 'https:') &&
      url.origin !== localOrigin
    ) {
      offOriginRequests.push(url.href);
    }
  };
  let finished = false;
  context.on('request', handleRequest);
  return () => {
    if (finished) {
      return;
    }
    finished = true;
    context.off('request', handleRequest);
    expect(
      offOriginRequests,
      'Every HTTP(S) request must stay on the local preview origin',
    ).toEqual([]);
  };
}

test.beforeEach(({ context }) => {
  localRequestAudits.set(context, startLocalRequestAudit(context));
});

test.afterEach(({ context }) => {
  localRequestAudits.get(context)?.();
  localRequestAudits.delete(context);
});

function modelSource(page: Page) {
  return page.getByRole('textbox', { name: 'Model source' });
}

function artifactOutput(page: Page) {
  return page.locator('.artifact-editor .view-lines');
}

function sourceOutput(page: Page) {
  return page.locator('.source-editor .view-lines');
}

async function focusSourceEditor(page: Page): Promise<void> {
  await sourceOutput(page).click({ position: { x: 8, y: 8 } });
  await expect(modelSource(page)).toBeFocused();
}

async function replaceSource(page: Page, text: string): Promise<void> {
  await focusSourceEditor(page);
  await page.keyboard.press('Control+a');
  await page.keyboard.press('Backspace');
  await expect(sourceOutput(page)).toHaveText('');
  await page.keyboard.type(text);
}

async function waitForReady(page: Page): Promise<void> {
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });
}

test('initializes locally and supports the complete editor workflow', async ({
  page,
}) => {
  test.setTimeout(90_000);
  let releaseManifest!: () => void;
  const manifestGate = new Promise<void>((resolve) => {
    releaseManifest = resolve;
  });
  await page.route(runtimeManifest, async (route) => {
    await manifestGate;
    await route.continue();
  });

  await page.goto('?test=1', { waitUntil: 'domcontentloaded' });
  expect(
    await page.evaluate(() => typeof globalThis.EditContext),
  ).toBe('function');
  const actions = [
    page.getByRole('button', { name: 'Validate' }),
    page.getByRole('button', { name: 'Format' }),
    page.getByRole('button', { name: 'Generate JSON Schema' }),
  ];
  await expect(page.getByRole('status')).toHaveText(/initializing compiler/i);
  for (const action of actions) {
    await expect(action).toBeDisabled();
  }
  releaseManifest();
  await waitForReady(page);
  await page.unroute(runtimeManifest);

  await expect(sourceOutput(page)).toContainText(/entity\s+Customer/);
  await replaceSource(page, invalidSource);
  await actions[0].click();
  await expect(page.getByTestId('diagnostics')).toContainText('PARSE');

  await replaceSource(page, validCompact);
  await actions[1].click();
  await expect
    .poll(() => page.locator('.source-editor .view-line').count())
    .toBeGreaterThan(1);
  await focusSourceEditor(page);
  await page.keyboard.press('Control+z');
  await expect(page.locator('.source-editor .view-line')).toHaveCount(1);
  await expect(sourceOutput(page)).toContainText(
    /domain\s+customer.*displayName\?:\s+string/,
  );
  await actions[1].click();
  await expect
    .poll(() => page.locator('.source-editor .view-line').count())
    .toBeGreaterThan(1);

  await actions[2].click();
  await expect(artifactOutput(page)).toContainText(
    /"title":\s+"Customer"/,
  );

  await replaceSource(page, `${validCompact}\n`);
  await expect(page.getByText(/stale.source changed/i)).toBeVisible();

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('discard unsaved changes');
    await dialog.accept();
  });
  await page.locator('input[type="file"]').setInputFiles({
    name: 'imported.mdl',
    mimeType: 'text/plain',
    buffer: Buffer.from(importedSource),
  });
  await expect(sourceOutput(page)).toContainText(/domain\s+imported/);

  const sourceDownloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export source' }).click();
  const sourceDownload = await sourceDownloadPromise;
  expect(sourceDownload.suggestedFilename()).toBe('imported.mdl');

  const artifactDownloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export artifact' }).click();
  const artifactDownload = await artifactDownloadPromise;
  expect(artifactDownload.suggestedFilename()).toMatch(/\.json$/);

  await expect(page.getByTestId('metrics')).toContainText(
    /initialization\s+\d+\.\d ms/i,
  );
  await expect(page.getByTestId('metrics')).toContainText(
    /operation\s+\d+\.\d ms/i,
  );
});

test('keeps keyboard access clear and treats hostile-looking source as text', async ({
  page,
}) => {
  await page.goto('?test=1');
  await waitForReady(page);

  await page.getByRole('link', { name: 'Skip to source' }).focus();
  await page.keyboard.press('Enter');
  await expect(modelSource(page)).toBeFocused();

  const hostileSource = [
    'globalThis.__modelablePwned = true;',
    '__import__("os").system("echo no")',
    '<img src=x onerror="globalThis.__modelablePwned=true">',
  ].join('\n');
  await replaceSource(page, hostileSource);
  await page.keyboard.press('Control+Shift+Enter');

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

test('retains the labeled textarea fallback when EditContext is unavailable', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis, 'EditContext', {
      configurable: true,
      value: undefined,
    });
  });
  await page.goto('');
  await waitForReady(page);

  const fallback = page.locator(
    'textarea[aria-label^="Model source"]',
  );
  await expect(fallback).toBeAttached();
  await page.getByRole('link', { name: 'Skip to source' }).focus();
  await page.keyboard.press('Enter');
  await expect(fallback).toBeFocused();

  await replaceSource(page, validCompact);
  await page.keyboard.press('Control+Shift+Enter');
  await expect(page.getByRole('status')).toHaveText(
    /validation complete/i,
  );
  await expect(page.getByTestId('diagnostics')).toContainText(
    'No diagnostics',
  );
});

test('has no automated accessibility violations when ready', async ({
  page,
}) => {
  await page.goto('');
  await waitForReady(page);

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test('allows Monaco to apply its runtime layout styles', async ({ page }) => {
  const cspViolations: string[] = [];
  page.on('console', (message) => {
    if (
      message.type() === 'error' &&
      message.text().includes('Content Security Policy')
    ) {
      cspViolations.push(message.text());
    }
  });

  await page.goto('');
  await waitForReady(page);

  expect(cspViolations).toEqual([]);
});

test('keeps the desktop editor workspace within a bounded page height', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('');
  await waitForReady(page);

  const dimensions = await page.evaluate(() => ({
    documentHeight: document.documentElement.scrollHeight,
    sourceEditorHeight:
      document.querySelector('.source-editor')?.getBoundingClientRect().height ??
      0,
    artifactEditorHeight:
      document
        .querySelector('.artifact-editor')
        ?.getBoundingClientRect().height ?? 0,
  }));

  expect(dimensions.documentHeight).toBeLessThanOrEqual(1440);
  expect(dimensions.sourceEditorHeight).toBeGreaterThanOrEqual(384);
  expect(dimensions.sourceEditorHeight).toBeLessThanOrEqual(720);
  expect(dimensions.artifactEditorHeight).toBe(
    dimensions.sourceEditorHeight,
  );
});

test('stacks both panes without horizontal overflow at 320 CSS pixels', async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto('');
  await waitForReady(page);

  const sourcePane = page.getByRole('region', { name: 'Modelable source' });
  const artifactPane = page.getByTestId('artifacts');
  const sourceBox = await sourcePane.boundingBox();
  const artifactBox = await artifactPane.boundingBox();
  expect(sourceBox).not.toBeNull();
  expect(artifactBox).not.toBeNull();
  expect(artifactBox!.y).toBeGreaterThan(sourceBox!.y + sourceBox!.height - 1);

  for (const control of await page
    .getByRole('navigation', { name: 'Playground actions' })
    .getByRole('button')
    .all()) {
    await control.scrollIntoViewIfNeeded();
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(320);
  }

  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth ===
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
});

test('does not expose the compiler client without explicit test opt-in', async ({
  page,
}) => {
  await page.goto('');
  await waitForReady(page);

  expect(
    await page.evaluate(
      () => '__modelableBrowserCompiler' in globalThis,
    ),
  ).toBe(false);
});

test('disposes the page client on pagehide exactly once', async ({ page }) => {
  await page.goto('?test=1');
  await waitForReady(page);

  const result = await page.evaluate(async () => {
    const client = (
      globalThis as typeof globalThis & {
        __modelableBrowserCompiler?: {
          openWorkspace(sources: unknown[]): Promise<unknown>;
          dispose(): void;
        };
      }
    ).__modelableBrowserCompiler;
    if (client === undefined) {
      throw new Error('Test client was not exposed');
    }
    globalThis.dispatchEvent(new PageTransitionEvent('pagehide'));
    globalThis.dispatchEvent(new PageTransitionEvent('pagehide'));
    return client.openWorkspace([]).then(
      () => ({ resolved: true }),
      (error: { message?: string }) => ({
        resolved: false,
        message: error.message,
      }),
    );
  });

  expect(result).toEqual({
    resolved: false,
    message: 'Compiler client has been disposed',
  });
});

test('retries a failed runtime manifest request without losing editor text', async ({
  page,
}) => {
  let failedOnce = false;
  await page.route(runtimeManifest, async (route) => {
    if (!failedOnce) {
      failedOnce = true;
      await route.abort();
      return;
    }
    await route.continue();
  });
  await page.goto('?test=1');
  await expect(page.locator('.status[role="alert"]')).toHaveText(
    /compiler runtime initialization failed/i,
    { timeout: 30_000 },
  );

  const retainedSource = 'domain retained { owner: "local" }';
  await replaceSource(page, retainedSource);
  await page.unroute(runtimeManifest);
  await page.getByRole('button', { name: 'Retry compiler' }).click();
  await waitForReady(page);
  await expect(sourceOutput(page)).toContainText(/domain\s+retained/);
});
