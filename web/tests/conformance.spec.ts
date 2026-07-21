import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
  type Request,
} from '@playwright/test';

type Source = { uri: string; text: string; version: number };
type TestClient = {
  openWorkspace(
    workspaceRevision: number,
    sources: Source[],
  ): Promise<unknown>;
  formatSource(source: Source): Promise<unknown>;
  compileJsonSchema(sources: Source[]): Promise<unknown>;
  completion(position: {
    workspaceRevision: number;
    uri: string;
    line: number;
    character: number;
  }): Promise<{ items: { label: string }[] }>;
  hover(position: {
    workspaceRevision: number;
    uri: string;
    line: number;
    character: number;
  }): Promise<{ hover: { markdown: string } | null }>;
};

const scenarios = {
  'invalid-parse': ['invalid-parse.mdl'],
  'invalid-reference': ['invalid-reference.mdl'],
  'invalid-semantic': ['invalid-semantic.mdl'],
  'multi-domain': ['multi-domain-customer.mdl', 'multi-domain-order.mdl'],
  'single-valid': ['single-valid.mdl'],
} as const;
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

test('browser compiler matches native snapshots including cross-file references', async ({
  page,
}) => {
  await page.goto('?test=1');
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });

  let workspaceRevision = 100;
  for (const [scenario, fixtureNames] of Object.entries(scenarios)) {
    const actual = await page.evaluate(
      async ({ fixtureNames, scenario, workspaceRevision }) => {
        const client = (
          globalThis as typeof globalThis & {
            __modelableBrowserCompiler?: TestClient;
          }
        ).__modelableBrowserCompiler;
        if (client === undefined) {
          throw new Error('Test client was not exposed');
        }
        const sources = await Promise.all(
          fixtureNames.map(async (name) => ({
            uri: `fixture:///${name}`,
            text: await (await fetch(`fixtures/${name}`)).text(),
            version: 1,
          })),
        );
        const result: Record<string, unknown> = {
          open: await client.openWorkspace(workspaceRevision, sources),
        };
        if (scenario === 'single-valid') {
          result.format = await client.formatSource(sources[0]!);
        }
        if (scenario === 'single-valid' || scenario === 'multi-domain') {
          result.compile = await client.compileJsonSchema(sources);
        }
        return result;
      },
      { fixtureNames, scenario, workspaceRevision },
    );
    workspaceRevision += 1;
    const expectedSnapshot = await (
      await page.request.get(`fixtures/${scenario}.json`)
    ).json();
    expectedSnapshot.open.workspace_revision = workspaceRevision - 1;

    expect(sortObject(actual)).toEqual(sortObject(expectedSnapshot));
  }
});

test('protocol v2 exposes completion and hover over the synchronized workspace', async ({
  page,
}) => {
  await page.goto('?test=1');
  await waitForCompiler(page);
  const result = await page.evaluate(async () => {
    const client = (
      globalThis as typeof globalThis & {
        __modelableBrowserCompiler?: TestClient;
      }
    ).__modelableBrowserCompiler;
    if (client === undefined) {
      throw new Error('Test client was not exposed');
    }
    const source: Source = {
      uri: 'file:///customer.mdl',
      text: [
        'domain customer {',
        '  owner: "team"',
        '  entity Customer @ 1 (additive) {',
        '    @key customer_id: uuid',
        '    customer_name: string',
        '  }',
        '}',
      ].join('\n'),
      version: 1,
    };
    const workspaceRevision = 100;
    await client.openWorkspace(workspaceRevision, [source]);
    const completion = await client.completion({
      workspaceRevision,
      uri: source.uri,
      line: 4,
      character: 4,
    });
    const hover = await client.hover({
      workspaceRevision,
      uri: source.uri,
      line: 3,
      character: 10,
    });
    return {
      labels: completion.items.map((item) => item.label),
      hover: hover.hover?.markdown ?? null,
    };
  });

  expect(result.labels).toEqual(
    expect.arrayContaining(['customer_id', 'customer_name']),
  );
  expect(result.hover).toContain('customer_id');
});

test('browser compiler stays within initialization and operation budgets', async ({
  browser,
}, testInfo) => {
  test.setTimeout(180_000);
  const cold = await measureColdInitializations(browser);
  const cachedContext = await browser.newContext();
  const finishCachedRequestAudit = startLocalRequestAudit(cachedContext);
  const cachedPage = await cachedContext.newPage();
  try {
    await initializePage(cachedPage);
    const cachedInitialize: number[] = [];
    const cachedPageReady: number[] = [];
    for (let index = 0; index < 3; index += 1) {
      const started = performance.now();
      await cachedPage.reload();
      await waitForCompiler(cachedPage);
      cachedPageReady.push(performance.now() - started);
      cachedInitialize.push(
        await readCompilerInitializationDuration(cachedPage),
      );
    }

    const operationTimings = await cachedPage.evaluate(async () => {
      const client = (
        globalThis as typeof globalThis & {
          __modelableBrowserCompiler?: TestClient;
        }
      ).__modelableBrowserCompiler;
      if (client === undefined) {
        throw new Error('Test client was not exposed');
      }
      const sources = [
        {
          uri: 'fixture:///budget.mdl',
          text: await (
            await fetch(new URL('fixtures/single-valid.mdl', location.href))
          ).text(),
          version: 1,
        },
      ];
      const validate: number[] = [];
      const compile: number[] = [];
      for (let index = 0; index < 3; index += 1) {
        let started = performance.now();
        await client.openWorkspace(index + 100, sources);
        validate.push(performance.now() - started);
        started = performance.now();
        await client.compileJsonSchema(sources);
        compile.push(performance.now() - started);
      }
      return { validate, compile };
    });

    const medians = {
      coldInitializeMedian: median(cold.runtimeInitialize),
      cachedInitializeMedian: median(cachedInitialize),
      validateMedian: median(operationTimings.validate),
      compileMedian: median(operationTimings.compile),
      coldPageReadyMedian: median(cold.pageReady),
      cachedPageReadyMedian: median(cachedPageReady),
    };
    const performanceReport = JSON.stringify(medians);
    testInfo.annotations.push({
      type: 'performance',
      description: performanceReport,
    });
    await testInfo.attach('performance-medians', {
      body: performanceReport,
      contentType: 'application/json',
    });
    console.log(`Browser performance medians: ${performanceReport}`);

    expect(medians.coldInitializeMedian).toBeLessThanOrEqual(20_000);
    expect(medians.cachedInitializeMedian).toBeLessThanOrEqual(10_000);
    expect(medians.validateMedian).toBeLessThanOrEqual(500);
    expect(medians.compileMedian).toBeLessThanOrEqual(1_000);
  } finally {
    try {
      finishCachedRequestAudit();
    } finally {
      await cachedContext.close();
    }
  }
});

async function measureColdInitializations(
  browser: Browser,
): Promise<{ runtimeInitialize: number[]; pageReady: number[] }> {
  const runtimeInitialize: number[] = [];
  const pageReady: number[] = [];
  for (let index = 0; index < 3; index += 1) {
    const context = await browser.newContext();
    const finishRequestAudit = startLocalRequestAudit(context);
    try {
      const page = await context.newPage();
      const started = performance.now();
      await initializePage(page);
      pageReady.push(performance.now() - started);
      runtimeInitialize.push(
        await readCompilerInitializationDuration(page),
      );
    } finally {
      try {
        finishRequestAudit();
      } finally {
        await context.close();
      }
    }
  }
  return { runtimeInitialize, pageReady };
}

async function initializePage(page: Page): Promise<void> {
  await page.goto('?test=1');
  await waitForCompiler(page);
}

async function waitForCompiler(page: Page): Promise<void> {
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });
}

async function readCompilerInitializationDuration(
  page: Page,
): Promise<number> {
  const rawDuration = await page
    .getByTestId('metrics')
    .getAttribute('data-initialization-duration-ms');
  if (rawDuration === null) {
    throw new Error('Compiler initialization duration was not exposed');
  }
  const duration = Number(rawDuration);
  if (!Number.isFinite(duration) || duration < 0) {
    throw new Error(
      `Compiler initialization duration is invalid: ${rawDuration}`,
    );
  }
  return duration;
}

function median(values: number[]): number {
  return [...values].sort((left, right) => left - right)[1]!;
}

function sortObject(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortObject);
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortObject(item)]),
    );
  }
  return value;
}
