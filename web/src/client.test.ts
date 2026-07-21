import { describe, expect, test } from 'vitest';

import {
  BrowserCompilerClient,
  BrowserCompilerError,
  type WorkerLike,
} from './client';
import type {
  BrowserCompilerRequest,
  BrowserCompilerResponse,
  BrowserSource,
} from './protocol';

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
    expect(worker.posted[3]?.payload).toEqual({ sources: [source] });
    worker.respond(
      success(worker.posted[3]!, { diagnostics: [], artifacts: [] }),
    );
    await compiled;
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
