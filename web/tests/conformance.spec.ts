import { expect, test } from '@playwright/test';

const scenarios = {
  'invalid-parse': ['invalid-parse.mdl'],
  'invalid-reference': ['invalid-reference.mdl'],
  'invalid-semantic': ['invalid-semantic.mdl'],
  'multi-domain': ['multi-domain-customer.mdl', 'multi-domain-order.mdl'],
  'single-valid': ['single-valid.mdl'],
} as const;

test('browser compiler matches every native snapshot', async ({ page }) => {
  await page.goto('?test=1');
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });

  for (const [scenario, fixtureNames] of Object.entries(scenarios)) {
    const actual = await page.evaluate(
      async ({ fixtureNames, scenario }) => {
        type Source = { uri: string; text: string; version: number };
        type TestClient = {
          openWorkspace(sources: Source[]): Promise<unknown>;
          formatSource(source: Source): Promise<unknown>;
          compileJsonSchema(sources: Source[]): Promise<unknown>;
        };
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
          open: await client.openWorkspace(sources),
        };
        if (scenario === 'single-valid') {
          result.format = await client.formatSource(sources[0]!);
        }
        if (scenario === 'single-valid' || scenario === 'multi-domain') {
          result.compile = await client.compileJsonSchema(sources);
        }
        return result;
      },
      { fixtureNames, scenario },
    );
    const expectedSnapshot = await (
      await page.request.get(`fixtures/${scenario}.json`)
    ).json();

    expect(sortObject(actual)).toEqual(sortObject(expectedSnapshot));
  }
});

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
