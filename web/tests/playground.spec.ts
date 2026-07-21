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
  await sourceOutput(page).click({
    position: { x: 8, y: 8 },
    force: true,
  });
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

async function createWorkspaceFile(
  page: Page,
  path: string,
  source: string,
): Promise<void> {
  await page.getByLabel('Workspace file path').fill(path);
  await page.getByRole('button', { name: 'New file' }).click();
  await replaceSource(page, source);
}

async function seedStoredWorkspace(page: Page, value: unknown): Promise<void> {
  await page.evaluate(async (record) => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('modelable-playground', 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains('workspaces')) {
          request.result.createObjectStore('workspaces', { keyPath: 'id' });
        }
      };
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const database = request.result;
        const transaction = database.transaction('workspaces', 'readwrite');
        transaction.objectStore('workspaces').put(record);
        transaction.oncomplete = () => {
          database.close();
          resolve();
        };
        transaction.onerror = () => reject(transaction.error);
      };
    });
  }, value);
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
  await expect(page.getByText('No artifact yet')).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Export artifact' }),
  ).toBeDisabled();

  await page
    .getByLabel('Import workspace files')
    .setInputFiles({
    name: 'imported.mdl',
    mimeType: 'text/plain',
    buffer: Buffer.from(importedSource),
  });
  await expect(sourceOutput(page)).toContainText(/domain\s+imported/);
  await actions[2].click();
  const artifactPicker = page.getByRole('combobox', {
    name: 'Artifact',
  });
  const importedArtifact = artifactPicker
    .locator('option')
    .filter({ hasText: 'Imported' });
  await expect(importedArtifact).toHaveCount(1);
  await artifactPicker.selectOption(
    (await importedArtifact.getAttribute('value')) ?? '',
  );
  await expect(artifactOutput(page)).toContainText(
    /"title":\s+"Imported"/,
  );

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

test('creates, validates, and restores a multi-file workspace', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.goto('?test=1');
  await waitForReady(page);
  await createWorkspaceFile(
    page,
    'customer.mdl',
    'domain customer { owner: "customer-team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
  );
  await page.getByRole('button', { name: 'main.mdl' }).click();
  await replaceSource(
    page,
    'domain sales { owner: "sales-team" entity Order @ 1 (additive) { @key orderId: uuid } }',
  );
  await page.getByRole('button', { name: 'Validate' }).click();
  await expect(page.getByRole('status')).toContainText(
    /validation complete.*0 diagnostics/i,
  );
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            globalThis as typeof globalThis & {
              __modelableWorkspaceSourceUris?: string[];
            }
          ).__modelableWorkspaceSourceUris,
      ),
    )
    .toEqual(['file:///customer.mdl', 'file:///main.mdl']);

  await page.getByRole('button', { name: 'customer.mdl' }).click();
  await expect(page.getByText('Saved locally')).toBeVisible();
  await page.reload();
  await waitForReady(page);
  await expect(
    page.getByRole('button', { name: 'customer.mdl' }),
  ).toHaveAttribute('aria-current', 'true');
  await expect(sourceOutput(page)).toContainText(/domain\s+customer/);
});

test('provides cross-file live diagnostics, completion, and hover accessibly', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.goto('?test=1');
  await waitForReady(page);
  const customerSource = [
    'domain imported {',
    '  owner: "team"',
    '  entity Imported @ 1 (additive) {',
    '    @key imported_id: uuid',
    '    imported_name: string',
    '  }',
    '}',
  ].join('\n');
  const orderSource =
    'domain sales { owner: "team" entity Order @ 1 (additive) { @key order_id: uuid } }';
  await page
    .getByLabel('Import workspace files')
    .setInputFiles([
      {
        name: 'customer.mdl',
        mimeType: 'text/plain',
        buffer: Buffer.from(customerSource),
      },
      {
        name: 'order.mdl',
        mimeType: 'text/plain',
        buffer: Buffer.from(orderSource),
      },
    ]);
  await page.getByRole('button', { name: 'order.mdl' }).click();
  await replaceSource(page, `${orderSource} {`);
  await expect(page.getByTestId('diagnostics')).toContainText('PARSE', {
    timeout: 10_000,
  });
  await replaceSource(page, orderSource);
  await expect(page.getByTestId('diagnostics')).toContainText(
    'No diagnostics',
    { timeout: 10_000 },
  );
  await expect(
    page.getByText('Synchronizing language services…'),
  ).toBeVisible();
  await expect(
    page.getByText('Language services synchronized'),
  ).toBeVisible({ timeout: 10_000 });

  await createWorkspaceFile(page, 'completion.mdl', 'dom');
  await expect(
    page.getByText('Synchronizing language services…'),
  ).toBeVisible();
  await expect(
    page.getByText('Language services synchronized'),
  ).toBeVisible({ timeout: 10_000 });
  await page.evaluate(() => {
    const target = globalThis as typeof globalThis & {
      __modelableBrowserCompiler?: {
        completion(...args: unknown[]): Promise<unknown>;
        hover(...args: unknown[]): Promise<unknown>;
      };
      __modelableCompletionInvoked?: boolean;
      __modelableHoverInvoked?: boolean;
      __modelableHoverResult?: unknown;
      __modelableHoverArgs?: unknown[];
    };
    const client = target.__modelableBrowserCompiler;
    if (client === undefined) {
      throw new Error('Test client was not exposed');
    }
    const completion = client.completion.bind(client);
    const hover = client.hover.bind(client);
    client.completion = async (...args) => {
      target.__modelableCompletionInvoked = true;
      return completion(...args);
    };
    client.hover = async (...args) => {
      target.__modelableHoverInvoked = true;
      target.__modelableHoverArgs = args;
      const result = await hover(...args);
      target.__modelableHoverResult = result;
      return result;
    };
  });
  await focusSourceEditor(page);
  await page.keyboard.press('Control+End');
  await page.keyboard.press('Control+Space');
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            globalThis as typeof globalThis & {
              __modelableCompletionInvoked?: boolean;
            }
          ).__modelableCompletionInvoked,
      ),
    )
    .toBe(true);
  await expect(page.locator('.suggest-widget')).toBeVisible();
  await expect(page.locator('.suggest-widget')).toContainText('domain');
  await page.keyboard.press('Escape');
  await expect(page.locator('.suggest-widget')).toBeHidden();

  await page.getByRole('button', { name: 'customer.mdl' }).click();
  await modelSource(page).focus();
  await expect(modelSource(page)).toBeFocused();
  await page.keyboard.press('Control+Home');
  for (let line = 0; line < 3; line += 1) {
    await page.keyboard.press('ArrowDown');
  }
  const hoverCharacter = 10;
  for (let index = 0; index < hoverCharacter; index += 1) {
    await page.keyboard.press('ArrowRight');
  }
  await page.keyboard.press('Control+k');
  await page.keyboard.press('Control+i');
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            globalThis as typeof globalThis & {
              __modelableHoverInvoked?: boolean;
            }
          ).__modelableHoverInvoked,
      ),
    )
    .toBe(true);
  expect(
    await page.evaluate(
      () =>
        (
          globalThis as typeof globalThis & {
            __modelableHoverArgs?: unknown[];
          }
        ).__modelableHoverArgs,
    ),
  ).toEqual([
    expect.objectContaining({
      uri: 'file:///customer.mdl',
      line: 3,
      character: hoverCharacter,
    }),
  ]);
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            globalThis as typeof globalThis & {
              __modelableHoverResult?: {
                hover?: { markdown?: string } | null;
              };
            }
          ).__modelableHoverResult?.hover?.markdown,
      ),
    )
    .toContain('imported_id');

  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth ===
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test('offers recovery without rendering corrupt stored source', async ({
  page,
}) => {
  await page.goto('?test=1');
  await waitForReady(page);
  await seedStoredWorkspace(page, {
    id: 'local',
    schemaVersion: 99,
    source: '<script>not markup</script>',
  });

  await page.reload();
  await expect(
    page.getByText('Stored workspace needs recovery'),
  ).toBeVisible();
  await expect(page.locator('body')).not.toContainText('not markup');
  await page.getByRole('button', { name: 'Reset local workspace' }).click();
  await expect(
    page.getByRole('button', { name: 'main.mdl' }),
  ).toBeVisible();
});

test('keeps editing available when IndexedDB is unavailable', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis, 'indexedDB', {
      configurable: true,
      value: undefined,
    });
  });
  await page.goto('?test=1');
  await waitForReady(page);
  await expect(page.getByText(/storage unavailable/i)).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Retry storage' }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Validate' })).toBeEnabled();
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

test('allows Monaco to apply its runtime styles and bundled icon font', async ({
  page,
}) => {
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
  await page.evaluate(async () => {
    const font = new FontFace(
      'modelable-csp-font-probe',
      'url(data:font/ttf;base64,AAEAAA==)',
    );
    await font.load().catch(() => undefined);
  });

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
          openWorkspace(
            workspaceRevision: number,
            sources: unknown[],
          ): Promise<unknown>;
          dispose(): void;
        };
      }
    ).__modelableBrowserCompiler;
    if (client === undefined) {
      throw new Error('Test client was not exposed');
    }
    globalThis.dispatchEvent(new PageTransitionEvent('pagehide'));
    globalThis.dispatchEvent(new PageTransitionEvent('pagehide'));
    return client.openWorkspace(1, []).then(
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
