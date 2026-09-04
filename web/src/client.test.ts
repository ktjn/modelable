import { describe, expect, test, vi } from 'vitest';

import {
  BrowserCompilerClient,
  BrowserCompilerError,
  type WorkerLike,
} from './client';
import type {
  BrowserCompilerRequest,
  BrowserCompilerResponse,
  BrowserFacetDocument,
  BrowserQueryRequest,
  BrowserSource,
} from './protocol';
import { validateRuntimeManifest } from './worker-support';

class FakeWorker implements WorkerLike {
  readonly posted: BrowserCompilerRequest[] = [];
  terminateCount = 0;
  readonly removed = {
    message: 0,
    error: 0,
  };
  private readonly messageListeners = new Set<
    (event: MessageEvent<unknown>) => void
  >();
  private readonly errorListeners = new Set<(event: ErrorEvent) => void>();

  postMessage(message: BrowserCompilerRequest): void {
    this.posted.push(message);
  }

  addEventListener(
    type: 'message' | 'error',
    listener:
      | ((event: MessageEvent<unknown>) => void)
      | ((event: ErrorEvent) => void),
  ): void {
    if (type === 'message') {
      this.messageListeners.add(
        listener as (event: MessageEvent<unknown>) => void,
      );
    } else {
      this.errorListeners.add(listener as (event: ErrorEvent) => void);
    }
  }

  removeEventListener(
    type: 'message' | 'error',
    listener:
      | ((event: MessageEvent<unknown>) => void)
      | ((event: ErrorEvent) => void),
  ): void {
    if (type === 'message') {
      this.messageListeners.delete(
        listener as (event: MessageEvent<unknown>) => void,
      );
      this.removed.message += 1;
    } else {
      this.errorListeners.delete(listener as (event: ErrorEvent) => void);
      this.removed.error += 1;
    }
  }

  terminate(): void {
    this.terminateCount += 1;
  }

  respond(response: BrowserCompilerResponse): void {
    for (const listener of this.messageListeners) {
      listener({ data: response } as MessageEvent<unknown>);
    }
  }

  fail(): void {
    for (const listener of this.errorListeners) {
      listener({ message: 'secret worker details' } as ErrorEvent);
    }
  }

  listenerCount(type: 'message' | 'error'): number {
    return type === 'message'
      ? this.messageListeners.size
      : this.errorListeners.size;
  }
}

function success(
  request: BrowserCompilerRequest,
  result: unknown,
): BrowserCompilerResponse {
  return {
    protocolVersion: 2,
    id: request.id,
    ok: true,
    result,
  };
}

function workspaceResult(workspaceRevision: number) {
  return {
    workspace_revision: workspaceRevision,
    diagnostics: [],
    source_hashes: {},
  };
}

async function initialize(
  client: BrowserCompilerClient,
  worker: FakeWorker,
): Promise<void> {
  const initialized = client.initialize();
  worker.respond(success(worker.posted[0]!, null));
  await initialized;
}

describe('BrowserCompilerClient', () => {
  test('accepts the bundled documentation runtime manifest with the network patch wheel', () => {
    const manifestUrl = new URL(
      'https://example.test/modelable/playground/python/runtime-manifest.json',
    );

    expect(validateRuntimeManifest({
      wheelUrls: [
        '/modelable/playground/python/lark-1.3.1-py3-none-any.whl',
        '/modelable/playground/python/modelable_browser-1.2.1-py3-none-any.whl',
        '/modelable/playground/python/pyodide_http-0.2.2-py3-none-any.whl',
        '/modelable/playground/python/searchable-2.0.1-py3-none-any.whl',
      ],
    }, manifestUrl)).toHaveLength(4);
  });

  test('shares one initialization request between concurrent callers', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);

    const first = client.initialize();
    const second = client.initialize();

    expect(worker.posted).toHaveLength(1);
    expect(worker.posted[0]?.method).toBe('runtime.initialize');
    worker.respond(success(worker.posted[0]!, null));
    await expect(Promise.all([first, second])).resolves.toEqual([
      undefined,
      undefined,
    ]);
  });

  test('fails only the active turn when provider completion fails', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);
    const providerError = new Error('provider unavailable');
    const provider = {
      id: 'failing',
      model: 'test',
      initialize: async () => {},
      complete: async () => {
        throw providerError;
      },
      dispose: async () => {},
    };

    const turn = client.conversationTurn(
      {
        sessionId: 'session-1',
        workspaceRevision: 1,
        message: 'Create customer.Customer',
        activeDocumentUri: null,
        position: null,
      },
      provider,
    );
    await Promise.resolve();
    worker.respond(
      success(worker.posted[1]!, {
        status: 'pending_llm',
        request_id: 'request-1',
        attempt: 0,
        llm_request: {
          system: 'Return a plan.',
          user: 'Create customer.Customer',
          temperature: 0.2,
          response_format: 'json',
          schema: { type: 'object' },
        },
      }),
    );
    await vi.waitFor(() => {
      expect(worker.posted[2]?.method).toBe('conversation.fail');
    });
    expect(worker.posted[2]?.payload).toEqual({
      sessionId: 'session-1',
      requestId: 'request-1',
      workspaceRevision: 1,
      error: 'provider unavailable',
    });
    worker.respond(
      success(worker.posted[2]!, {
        reply: {
          kind: 'unsupported',
          text: 'Provider unavailable',
          change_set_id: null,
          operation_kind: null,
          focused_ref: null,
          preview_files: [],
          compilation_files: [],
        },
        workspace_revision: 1,
        sources: [],
      }),
    );
    await expect(turn).rejects.toBe(providerError);
  });

  test('serializes automatic documentation policy and normalizes retrieval metadata', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);
    const provider = {
      id: 'test',
      model: 'test',
      initialize: async () => {},
      complete: async () => ({
        content: 'unused',
        provider: 'test',
        model: 'test',
      }),
      dispose: async () => {},
    };

    const turn = client.conversationTurn(
      {
        sessionId: 'session-1',
        workspaceRevision: 1,
        message: 'How do I configure the compiler?',
        activeDocumentUri: null,
        position: null,
        documentationIndexUrl: 'https://example.test/docs-index/manifest.json',
        documentationAssetRoot: 'https://example.test/docs-index/',
        automaticDocumentation: false,
      },
      provider,
    );
    await Promise.resolve();

    expect(worker.posted[1]?.payload).toEqual({
      sessionId: 'session-1',
      workspaceRevision: 1,
      message: 'How do I configure the compiler?',
      activeDocumentUri: null,
      line: null,
      character: null,
      documentationIndexUrl: 'https://example.test/docs-index/manifest.json',
      documentationAssetRoot: 'https://example.test/docs-index/',
      automaticDocumentation: false,
    });
    worker.respond(
      success(worker.posted[1]!, {
        reply: {
          kind: 'answer',
          text: 'Use the configuration guide.',
          change_set_id: null,
          operation_kind: null,
          focused_ref: null,
          assumptions: [],
          changed: [],
          affected: [],
          preview_files: [],
          compilation_files: [],
          retrieval_used: true,
          route_reason: 'automatic_documentation_signal',
          citations: [{
            label: 'S1',
            external_id: 'guide.md#configuration',
            url: 'https://example.test/guide/#configuration',
            title: 'Guide',
            heading: 'Configuration',
            score: 0.9,
          }],
        },
        workspace_revision: 1,
        sources: [],
      }),
    );

    await expect(turn).resolves.toMatchObject({
      reply: {
        retrievalUsed: true,
        routeReason: 'automatic_documentation_signal',
        citations: [{
          label: 'S1',
          externalId: 'guide.md#configuration',
          url: 'https://example.test/guide/#configuration',
        }],
      },
    });
  });

  test('continues with the planner after an automatic documentation provider failure', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);
    let completions = 0;
    const provider = {
      id: 'flaky',
      model: 'test',
      initialize: async () => {},
      complete: async () => {
        completions += 1;
        if (completions === 1) {
          throw new Error('documentation generation failed');
        }
        return {
          content: '{"kind":"query"}',
          provider: 'flaky',
          model: 'test',
        };
      },
      dispose: async () => {},
    };

    const turn = client.conversationTurn(
      {
        sessionId: 'session-1',
        workspaceRevision: 1,
        message: 'How do I configure the compiler?',
        activeDocumentUri: null,
        position: null,
      },
      provider,
    );
    await Promise.resolve();
    worker.respond(success(worker.posted[1]!, {
      status: 'pending_llm',
      request_id: 'docs-request',
      attempt: 0,
      llm_request: {
        system: 'Answer from documentation.',
        user: 'Documentation evidence',
        temperature: 0.2,
        response_format: 'text',
        schema: null,
      },
    }));
    await vi.waitFor(() => {
      expect(worker.posted[2]?.method).toBe('conversation.fail');
    });
    worker.respond(success(worker.posted[2]!, {
      status: 'pending_llm',
      request_id: 'planner-request',
      attempt: 0,
      llm_request: {
        system: 'Return a plan.',
        user: 'How do I configure the compiler?',
        temperature: 0.2,
        response_format: 'json',
        schema: { type: 'object' },
      },
    }));
    await vi.waitFor(() => {
      expect(worker.posted[3]?.method).toBe('conversation.resume');
    });
    worker.respond(success(worker.posted[3]!, {
      reply: {
        kind: 'answer',
        text: 'Ordinary planner answer',
        change_set_id: null,
        operation_kind: null,
        focused_ref: null,
        assumptions: [],
        changed: [],
        affected: [],
        preview_files: [],
        compilation_files: [],
      },
      workspace_revision: 1,
      sources: [],
    }));

    await expect(turn).resolves.toMatchObject({
      reply: { text: 'Ordinary planner answer' },
    });
    expect(completions).toBe(2);
  });

  test('response IDs resolve only matching promises', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);

    const first = client.openWorkspace(1, [
      { uri: 'first.mdl', text: 'first', version: 1 },
    ]);
    const second = client.openWorkspace(2, [
      { uri: 'second.mdl', text: 'second', version: 2 },
    ]);
    await Promise.resolve();
    const firstRequest = worker.posted[1]!;
    const secondRequest = worker.posted[2]!;

    let firstSettled = false;
    void first.finally(() => {
      firstSettled = true;
    });
    worker.respond(success(secondRequest, workspaceResult(2)));
    await expect(second).resolves.toEqual(workspaceResult(2));
    expect(firstSettled).toBe(false);
    worker.respond(success(firstRequest, workspaceResult(1)));
    await expect(first).resolves.toEqual(workspaceResult(1));
  });

  test('worker errors reject every pending request with sanitized failures', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);

    const first = client.openWorkspace(1, [
      { uri: 'first.mdl', text: 'first', version: 1 },
    ]);
    const second = client.formatSource({
      uri: 'second.mdl',
      text: 'second',
      version: 1,
    });
    worker.fail();

    for (const request of [first, second]) {
      await expect(request).rejects.toMatchObject({
        code: 'COMPILER_FAILED',
        message: 'Compiler worker failed',
      });
    }
    expect(worker.removed).toEqual({ message: 1, error: 1 });
    expect(worker.listenerCount('message')).toBe(0);
    expect(worker.listenerCount('error')).toBe(0);
    expect(worker.terminateCount).toBe(1);

    client.dispose();
    client.dispose();
    expect(worker.terminateCount).toBe(1);
  });

  test('malformed responses reject pending work and clean up exactly once', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    const pending = client.initialize();

    worker.respond({ unexpected: 'response' } as never);

    await expect(pending).rejects.toMatchObject({
      code: 'COMPILER_FAILED',
      message: 'Compiler worker returned an invalid response',
    });
    expect(worker.removed).toEqual({ message: 1, error: 1 });
    expect(worker.listenerCount('message')).toBe(0);
    expect(worker.listenerCount('error')).toBe(0);
    expect(worker.terminateCount).toBe(1);

    worker.fail();
    client.dispose();
    expect(worker.terminateCount).toBe(1);
  });

  test('typed failures reject with BrowserCompilerError code', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    const initialized = client.initialize();
    worker.respond({
      protocolVersion: 2,
      id: worker.posted[0]!.id,
      ok: false,
      error: {
        code: 'INITIALIZATION_FAILED',
        message: 'Runtime unavailable',
      },
    });

    const error = await initialized.catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(BrowserCompilerError);
    expect(error).toMatchObject({
      code: 'INITIALIZATION_FAILED',
      message: 'Runtime unavailable',
    });
  });

  test('post-disposal calls reject without posting', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    client.dispose();

    await expect(client.initialize()).rejects.toMatchObject({
      code: 'COMPILER_FAILED',
    });
    await expect(
      client.openWorkspace(1, [
        { uri: 'x.mdl', text: 'x', version: 1 },
      ]),
    ).rejects.toMatchObject({ code: 'COMPILER_FAILED' });
    expect(worker.posted).toHaveLength(0);
    expect(worker.terminateCount).toBe(1);
  });

  test('dispose rejects pending requests and terminates the worker', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    const pending = client.initialize();

    client.dispose();
    client.dispose();

    await expect(pending).rejects.toMatchObject({ code: 'COMPILER_FAILED' });
    expect(worker.removed).toEqual({ message: 1, error: 1 });
    expect(worker.terminateCount).toBe(1);
  });

  test('source DTOs preserve uri, text, and version', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);
    const source: BrowserSource = {
      uri: 'memory://demo.mdl',
      text: 'domain Demo',
      version: 7,
    };

    const opened = client.openWorkspace(7, [source]);
    await Promise.resolve();
    expect(worker.posted[1]?.payload).toEqual({
      workspaceRevision: 7,
      sources: [source],
    });
    worker.respond(success(worker.posted[1]!, workspaceResult(7)));
    await opened;

    const formatted = client.formatSource(source);
    await Promise.resolve();
    expect(worker.posted[2]?.payload).toEqual({ source });
    worker.respond(
      success(worker.posted[2]!, {
        diagnostics: [],
        replacement_text: null,
      }),
    );
    await formatted;

    const compiled = client.compileJsonSchema([source]);
    await Promise.resolve();
    expect(worker.posted[3]?.payload).toEqual({
      sources: [source],
      target: 'jsonSchema',
    });
    worker.respond(
      success(worker.posted[3]!, { diagnostics: [], artifacts: [] }),
    );
    await compiled;

    const plans = client.plans(7);
    await Promise.resolve();
    expect(worker.posted[4]?.method).toBe('workspace.plans');
    expect(worker.posted[4]?.payload).toEqual({ workspaceRevision: 7 });
    worker.respond(
      success(worker.posted[4]!, {
        workspace_revision: 7,
        plans: [
          JSON.stringify({
            $schema: 'modelable.plan/v1',
            domain: 'billing',
            projection: 'BillingCustomer',
            version: 1,
            auto_generated: false,
            requires_revalidation: false,
            revalidation_reasons: [],
            governance_findings: [],
            source: {},
            joins: [],
            group_by: [],
            fields: [],
            planner_metadata: {},
          }),
        ],
      }),
    );
    await plans;
  });

  test('workspace.open sends an explicit typed facet document', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);
    const source: BrowserSource = {
      uri: 'memory://demo.mdl',
      text: 'domain Demo',
      version: 1,
    };
    const facetsDocument: BrowserFacetDocument = {
      $schema: 'modelable.facets/v1',
      schemas: [],
      facets: [],
    };

    const opened = client.openWorkspace(8, [source], facetsDocument);
    await Promise.resolve();

    expect(worker.posted[1]).toMatchObject({
      method: 'workspace.open',
      payload: {
        workspaceRevision: 8,
        sources: [source],
        facetsDocument,
      },
    });
    worker.respond(success(worker.posted[1]!, workspaceResult(8)));
    await expect(opened).resolves.toEqual(workspaceResult(8));
  });

  test('workspace.query sends a typed facet request and returns its response', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);
    const request: BrowserQueryRequest = {
      $schema: 'modelable.query/v1',
      kind: 'query',
      query: 'facets',
      id: 'customer.Customer@1#name',
    };
    const response = {
      $schema: 'modelable.query/v1',
      kind: 'query_result' as const,
      query: 'facets' as const,
      data: { facets: [] },
    };

    const queried = client.query(8, request);
    await Promise.resolve();

    expect(worker.posted[1]).toMatchObject({
      method: 'workspace.query',
      payload: { workspaceRevision: 8, request },
    });
    worker.respond(success(worker.posted[1]!, response));
    await expect(queried).resolves.toEqual(response);
  });

  test('workspace.query rejects a malformed result from the compiler', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);
    const queried = client.query(8, {
      $schema: 'modelable.query/v1',
      kind: 'query',
      query: 'facets',
      id: 'customer.Customer@1#name',
    });
    await Promise.resolve();

    worker.respond(
      success(worker.posted[1]!, {
        $schema: 'modelable.query/v1',
        kind: 'query_result',
        query: 'facets',
      }),
    );

    await expect(queried).rejects.toMatchObject({ code: 'COMPILER_FAILED' });
  });

  test('opens a numbered workspace and sends typed language positions', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);
    const source: BrowserSource = {
      uri: 'file:///demo.mdl',
      text: 'domain Demo',
      version: 7,
    };

    const opened = client.openWorkspace(4, [source]);
    await Promise.resolve();
    expect(worker.posted[1]?.payload).toEqual({
      workspaceRevision: 4,
      sources: [source],
    });
    worker.respond(
      success(worker.posted[1]!, {
        workspace_revision: 4,
        diagnostics: [],
        source_hashes: { 'file:///demo.mdl': 'abc' },
      }),
    );
    await opened;

    const completion = client.completion({
      workspaceRevision: 4,
      uri: source.uri,
      line: 1,
      character: 2,
    });
    await Promise.resolve();
    expect(worker.posted[2]?.method).toBe('language.completion');
    expect(worker.posted[2]?.payload).toEqual({
      workspaceRevision: 4,
      uri: source.uri,
      line: 1,
      character: 2,
    });
    worker.respond(success(worker.posted[2]!, { items: [] }));
    await expect(completion).resolves.toEqual({ items: [] });

    const hover = client.hover({
      workspaceRevision: 4,
      uri: source.uri,
      line: 1,
      character: 2,
    });
    await Promise.resolve();
    expect(worker.posted[3]?.method).toBe('language.hover');
    worker.respond(success(worker.posted[3]!, { hover: null }));
    await expect(hover).resolves.toEqual({ hover: null });

    const definition = client.definition({
      workspaceRevision: 4,
      uri: source.uri,
      line: 1,
      character: 2,
    });
    await Promise.resolve();
    expect(worker.posted[4]?.method).toBe('language.definition');
    expect(worker.posted[4]?.payload).toEqual({
      workspaceRevision: 4,
      uri: source.uri,
      line: 1,
      character: 2,
    });
    worker.respond(success(worker.posted[4]!, { location: null }));
    await expect(definition).resolves.toEqual({ location: null });

    const references = client.references(
      { workspaceRevision: 4, uri: source.uri, line: 1, character: 2 },
      true,
    );
    await Promise.resolve();
    expect(worker.posted[5]?.method).toBe('language.references');
    expect(worker.posted[5]?.payload).toEqual({
      workspaceRevision: 4,
      uri: source.uri,
      line: 1,
      character: 2,
      includeDeclaration: true,
    });
    worker.respond(success(worker.posted[5]!, { locations: [] }));
    await expect(references).resolves.toEqual({ locations: [] });

    const prepareRename = client.prepareRename({
      workspaceRevision: 4,
      uri: source.uri,
      line: 1,
      character: 2,
    });
    await Promise.resolve();
    expect(worker.posted[6]?.method).toBe('language.prepareRename');
    worker.respond(success(worker.posted[6]!, { prepared: null }));
    await expect(prepareRename).resolves.toEqual({ prepared: null });

    const rename = client.rename(
      { workspaceRevision: 4, uri: source.uri, line: 1, character: 2 },
      'Client',
    );
    await Promise.resolve();
    expect(worker.posted[7]?.method).toBe('language.rename');
    expect(worker.posted[7]?.payload).toEqual({
      workspaceRevision: 4,
      uri: source.uri,
      line: 1,
      character: 2,
      newName: 'Client',
    });
    worker.respond(success(worker.posted[7]!, { edit: { edits: [] } }));
    await expect(rename).resolves.toEqual({ edit: { edits: [] } });
  });

  test('invalid success payloads transition the client to terminal failure', async () => {
    const worker = new FakeWorker();
    const client = new BrowserCompilerClient(worker);
    await initialize(client, worker);

    const completion = client.completion({
      workspaceRevision: 1,
      uri: 'file:///demo.mdl',
      line: 0,
      character: 0,
    });
    await Promise.resolve();
    worker.respond(
      success(worker.posted[1]!, {
        items: [{ label: 'x', extra: true }],
      }),
    );

    await expect(completion).rejects.toMatchObject({
      code: 'COMPILER_FAILED',
      message: 'Compiler worker returned an invalid result',
    });
    expect(worker.terminateCount).toBe(1);
    await expect(client.hover({
      workspaceRevision: 1,
      uri: 'file:///demo.mdl',
      line: 0,
      character: 0,
    })).rejects.toMatchObject({ code: 'COMPILER_FAILED' });
  });
});
