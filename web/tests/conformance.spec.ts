import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
  type Request,
} from '@playwright/test';

type Source = { uri: string; text: string; version: number };
type LanguagePosition = {
  workspaceRevision: number;
  uri: string;
  line: number;
  character: number;
};
type LanguageLocation = {
  uri: string;
  range: {
    start: { line: number; character: number };
    end: { line: number; character: number };
  };
};
type TestClient = {
  openWorkspace(
    workspaceRevision: number,
    sources: Source[],
  ): Promise<unknown>;
  formatSource(source: Source): Promise<unknown>;
  compileJsonSchema(sources: Source[]): Promise<unknown>;
  completion(
    position: LanguagePosition,
  ): Promise<{ items: { label: string }[] }>;
  hover(
    position: LanguagePosition,
  ): Promise<{ hover: { markdown: string } | null }>;
  definition(
    position: LanguagePosition,
  ): Promise<{ location: LanguageLocation | null }>;
  references(
    position: LanguagePosition,
    includeDeclaration: boolean,
  ): Promise<{ locations: LanguageLocation[] }>;
  prepareRename(
    position: LanguagePosition,
  ): Promise<{
    prepared: {
      range: LanguageLocation['range'];
      placeholder: string;
    } | null;
  }>;
  rename(
    position: LanguagePosition,
    newName: string,
  ): Promise<{
    edit: {
      edits: {
        uri: string;
        range: LanguageLocation['range'];
        new_text: string;
        expected_version: number;
        expected_hash: string;
      }[];
    };
  }>;
  graph(
    workspaceRevision: number,
    mode: string,
  ): Promise<{
    workspace_revision: number;
    mode: string;
    graph: {
      schema_version: number;
      nodes: { id: string; kind: string; label: string }[];
      edges: { id: string; source: string; target: string; kind: string }[];
    };
  }>;
  lineage(workspaceRevision: number): Promise<{
    workspace_revision: number;
    projections: {
      domain: string;
      projection: string;
      version: number;
      fields: {
        field_name: string;
        kind: string;
        lineage: string[];
        expression: string | null;
      }[];
    }[];
  }>;
  compatibility(workspaceRevision: number): Promise<{
    workspace_revision: number;
    reports: {
      domain_name: string;
      model_name: string;
      from_version: number;
      to_version: number;
      status: string;
      findings: string[];
      changes: {
        kind: string;
        field_name: string;
        previous_name: string | null;
        replacement: string | null;
        from_optional: boolean | null;
        to_optional: boolean | null;
        from_type: string | null;
        to_type: string | null;
      }[];
    }[];
    impacts: {
      domain_name: string;
      projection_name: string;
      version: number;
      status: string;
      reason: string | null;
    }[];
  }>;
  governance(workspaceRevision: number): Promise<{
    workspace_revision: number;
    findings: {
      code: string;
      subject: string;
      message: string;
    }[];
  }>;
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
  await expect(page.locator('main.workbench')).not.toHaveAttribute('data-state', 'loading', {
    timeout: 90_000,
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

test('protocol v2 exposes definition, references, prepareRename, and rename', async ({
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
    const workspaceRevision = 200;
    await client.openWorkspace(workspaceRevision, [source]);

    const definition = await client.definition({
      workspaceRevision,
      uri: source.uri,
      line: 2,
      character: 10,
    });

    const references = await client.references(
      {
        workspaceRevision,
        uri: source.uri,
        line: 3,
        character: 10,
      },
      true,
    );

    const prepareRename = await client.prepareRename({
      workspaceRevision,
      uri: source.uri,
      line: 2,
      character: 10,
    });

    const rename = await client.rename(
      {
        workspaceRevision,
        uri: source.uri,
        line: 2,
        character: 10,
      },
      'Client',
    );

    return { definition, references, prepareRename, rename };
  });

  expect(result.definition.location).not.toBeNull();
  expect(result.definition.location!.uri).toBe('file:///customer.mdl');
  expect(result.definition.location!.range.start.line).toBe(2);

  expect(result.references.locations.length).toBeGreaterThanOrEqual(1);

  expect(result.prepareRename.prepared).not.toBeNull();
  expect(result.prepareRename.prepared!.placeholder).toBe('Customer');

  expect(result.rename.edit.edits.length).toBeGreaterThanOrEqual(1);
  expect(result.rename.edit.edits[0]!.new_text).toBe('Client');
});

test('workspace.graph returns domain and entity mode graphs', async ({
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
    const workspaceRevision = 300;
    await client.openWorkspace(workspaceRevision, [source]);

    const entity = await client.graph(workspaceRevision, 'entity');
    const domain = await client.graph(workspaceRevision, 'domain');
    return { entity, domain };
  });

  expect(result.entity.workspace_revision).toBe(300);
  expect(result.entity.mode).toBe('entity');
  expect(result.entity.graph.schema_version).toBe(1);
  expect(result.entity.graph.nodes.length).toBeGreaterThan(0);
  expect(result.entity.graph.edges.length).toBeGreaterThan(0);
  const entityKinds = new Set(
    result.entity.graph.nodes.map((n: { kind: string }) => n.kind),
  );
  expect(entityKinds).toContain('domain');
  expect(entityKinds).toContain('entity');
  expect(entityKinds).toContain('version');
  expect(entityKinds).toContain('field');

  expect(result.domain.mode).toBe('domain');
  const domainKinds = new Set(
    result.domain.graph.nodes.map((n: { kind: string }) => n.kind),
  );
  expect(domainKinds).toContain('domain');
  expect(domainKinds).toContain('entity');
  expect(domainKinds).not.toContain('version');
  expect(domainKinds).not.toContain('field');
});

test('workspace.graph returns projection and lineage mode graphs', async ({
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
        '  projection CustomerView @ 1',
        '    from customer.Customer @ 1 as c',
        '  {',
        '    id <- c.customer_id',
        '    name = c.customer_name',
        '  }',
        '}',
      ].join('\n'),
      version: 1,
    };
    const workspaceRevision = 350;
    await client.openWorkspace(workspaceRevision, [source]);

    const projection = await client.graph(workspaceRevision, 'projection');
    const lineage = await client.graph(workspaceRevision, 'lineage');
    return { projection, lineage };
  });

  expect(result.projection.mode).toBe('projection');
  expect(result.projection.graph.nodes.length).toBeGreaterThan(0);
  const projKinds = new Set(
    result.projection.graph.nodes.map((n: { kind: string }) => n.kind),
  );
  expect(projKinds).toContain('projection');
  expect(projKinds).toContain('field');
  expect(projKinds).not.toContain('domain');

  expect(result.lineage.mode).toBe('lineage');
  expect(result.lineage.graph.nodes.length).toBeGreaterThan(0);
  const lineageKinds = new Set(
    result.lineage.graph.nodes.map((n: { kind: string }) => n.kind),
  );
  expect(lineageKinds).toEqual(new Set(['field']));
  const lineageEdgeKinds = new Set(
    result.lineage.graph.edges.map((e: { kind: string }) => e.kind),
  );
  expect(lineageEdgeKinds).toEqual(new Set(['projects']));
});

test('workspace.lineage, workspace.compatibility, and workspace.governance return analysis results', async ({
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
    const customerSource: Source = {
      uri: 'file:///customer.mdl',
      text: [
        'domain customer {',
        '  owner: "customer-platform"',
        '  entity Customer @ 1 (additive) {',
        '    @key customerId: uuid',
        '    displayName: string',
        '  }',
        '  entity Customer @ 2 (additive) {',
        '    @key customerId: uuid',
        '    displayName: string',
        '    email: string',
        '  }',
        '}',
      ].join('\n'),
      version: 1,
    };
    const billingSource: Source = {
      uri: 'file:///billing.mdl',
      text: [
        'domain billing {',
        '  owner: "billing-platform"',
        '  projection BillingCustomer @ 1 from customer.Customer @ 2 as c {',
        '    id = c.customerId',
        '    name = c.displayName',
        '  }',
        '}',
      ].join('\n'),
      version: 1,
    };
    const workspaceRevision = 400;
    await client.openWorkspace(workspaceRevision, [
      customerSource,
      billingSource,
    ]);

    const lineage = await client.lineage(workspaceRevision);
    const compatibility = await client.compatibility(workspaceRevision);
    const governance = await client.governance(workspaceRevision);
    return { lineage, compatibility, governance };
  });

  expect(result.lineage.workspace_revision).toBe(400);
  expect(result.lineage.projections.length).toBeGreaterThan(0);
  const billingProjection = result.lineage.projections.find(
    (p) => p.projection === 'BillingCustomer',
  );
  expect(billingProjection).toBeDefined();
  expect(billingProjection!.domain).toBe('billing');
  expect(billingProjection!.fields.length).toBeGreaterThan(0);
  const idField = billingProjection!.fields.find(
    (f) => f.field_name === 'id',
  );
  expect(idField).toBeDefined();
  expect(['direct', 'computed']).toContain(idField!.kind);
  expect(idField!.lineage.length).toBeGreaterThan(0);

  expect(result.compatibility.workspace_revision).toBe(400);
  expect(result.compatibility.reports.length).toBeGreaterThan(0);
  const customerReport = result.compatibility.reports.find(
    (r) => r.model_name === 'Customer',
  );
  expect(customerReport).toBeDefined();
  expect(customerReport!.from_version).toBe(1);
  expect(customerReport!.to_version).toBe(2);
  expect(customerReport!.changes.length).toBeGreaterThan(0);

  expect(result.governance.workspace_revision).toBe(400);
  expect(Array.isArray(result.governance.findings)).toBe(true);
});

test('browser compiler stays within initialization and operation budgets', async ({
  browser,
  browserName,
}, testInfo) => {
  test.setTimeout(600_000);
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
      const completion: number[] = [];
      const hover: number[] = [];
      const definition: number[] = [];
      const references: number[] = [];
      const prepareRename: number[] = [];
      const rename: number[] = [];
      const graph: number[] = [];
      const lineage: number[] = [];
      const compatibility: number[] = [];
      const governance: number[] = [];
      const languagePosition = {
        workspaceRevision: 100,
        uri: sources[0]!.uri,
        line: 2,
        character: 10,
      };
      for (let index = 0; index < 3; index += 1) {
        let started = performance.now();
        await client.openWorkspace(index + 100, sources);
        validate.push(performance.now() - started);
        languagePosition.workspaceRevision = index + 100;

        started = performance.now();
        await client.compileJsonSchema(sources);
        compile.push(performance.now() - started);

        started = performance.now();
        await client.completion(languagePosition);
        completion.push(performance.now() - started);

        started = performance.now();
        await client.hover(languagePosition);
        hover.push(performance.now() - started);

        started = performance.now();
        await client.definition(languagePosition);
        definition.push(performance.now() - started);

        started = performance.now();
        await client.references(languagePosition, true);
        references.push(performance.now() - started);

        const renamePosition = {
          workspaceRevision: languagePosition.workspaceRevision,
          uri: sources[0]!.uri,
          line: 8,
          character: 9,
        };
        started = performance.now();
        await client.prepareRename(renamePosition);
        prepareRename.push(performance.now() - started);

        started = performance.now();
        await client.rename(renamePosition, `Client${index}`);
        rename.push(performance.now() - started);

        started = performance.now();
        await client.graph(languagePosition.workspaceRevision, 'entity');
        graph.push(performance.now() - started);

        started = performance.now();
        await client.lineage(languagePosition.workspaceRevision);
        lineage.push(performance.now() - started);

        started = performance.now();
        await client.compatibility(languagePosition.workspaceRevision);
        compatibility.push(performance.now() - started);

        started = performance.now();
        await client.governance(languagePosition.workspaceRevision);
        governance.push(performance.now() - started);
      }
      return {
        validate,
        compile,
        completion,
        hover,
        definition,
        references,
        prepareRename,
        rename,
        graph,
        lineage,
        compatibility,
        governance,
      };
    });

    const medians = {
      coldInitializeMedian: median(cold.runtimeInitialize),
      cachedInitializeMedian: median(cachedInitialize),
      validateMedian: median(operationTimings.validate),
      compileMedian: median(operationTimings.compile),
      completionMedian: median(operationTimings.completion),
      hoverMedian: median(operationTimings.hover),
      definitionMedian: median(operationTimings.definition),
      referencesMedian: median(operationTimings.references),
      prepareRenameMedian: median(operationTimings.prepareRename),
      renameMedian: median(operationTimings.rename),
      graphMedian: median(operationTimings.graph),
      lineageMedian: median(operationTimings.lineage),
      compatibilityMedian: median(operationTimings.compatibility),
      governanceMedian: median(operationTimings.governance),
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

    const m = browserName === 'firefox' ? 2.5 : 1;
    expect(medians.coldInitializeMedian).toBeLessThanOrEqual(20_000 * m);
    expect(medians.cachedInitializeMedian).toBeLessThanOrEqual(10_000 * m);
    expect(medians.validateMedian).toBeLessThanOrEqual(500 * m);
    expect(medians.compileMedian).toBeLessThanOrEqual(1_000 * m);
    expect(medians.completionMedian).toBeLessThanOrEqual(100 * m);
    expect(medians.hoverMedian).toBeLessThanOrEqual(100 * m);
    expect(medians.definitionMedian).toBeLessThanOrEqual(150 * m);
    expect(medians.referencesMedian).toBeLessThanOrEqual(150 * m);
    expect(medians.prepareRenameMedian).toBeLessThanOrEqual(250 * m);
    expect(medians.renameMedian).toBeLessThanOrEqual(250 * m);
    expect(medians.graphMedian).toBeLessThanOrEqual(200 * m);
    expect(medians.lineageMedian).toBeLessThanOrEqual(500 * m);
    expect(medians.compatibilityMedian).toBeLessThanOrEqual(500 * m);
    expect(medians.governanceMedian).toBeLessThanOrEqual(500 * m);
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
  await expect(page.locator('main.workbench')).not.toHaveAttribute('data-state', 'loading', {
    timeout: 90_000,
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
