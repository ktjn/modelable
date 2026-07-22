import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import {
  BrowserCompilerError,
  type BrowserCompilerClientLike,
} from '../client';
import type {
  BrowserCompletionResult,
  BrowserDefinitionResult,
  BrowserDiagnostic,
  BrowserHoverResult,
  BrowserLanguagePosition,
  BrowserPreparedRenameResult,
  BrowserReferencesResult,
  BrowserGraphResult,
  BrowserRenameResult,
  BrowserSource,
  BrowserWorkspaceResult,
} from '../protocol';
import type { PlaygroundWorkspace } from '../workspace';
import { BrowserLanguageServiceController } from './BrowserLanguageServiceController';

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

function workspaceAt(revision: number): PlaygroundWorkspace {
  return {
    schemaVersion: 1,
    id: 'local',
    revision,
    activeFile: 'main.mdl',
    files: [
      {
        path: 'main.mdl',
        content: `domain Revision${revision}`,
        version: revision,
      },
    ],
  };
}

function sourcesAt(revision: number): BrowserSource[] {
  return [
    {
      uri: 'file:///main.mdl',
      text: `domain Revision${revision}`,
      version: revision,
    },
  ];
}

function opened(
  revision: number,
  diagnostics: BrowserDiagnostic[] = [],
): BrowserWorkspaceResult {
  return {
    workspace_revision: revision,
    diagnostics,
    source_hashes: { 'file:///main.mdl': `hash-${revision}` },
  };
}

class FakeClient implements BrowserCompilerClientLike {
  readonly initialize = vi.fn(async () => undefined);
  readonly openWorkspace = vi.fn(
    (_revision: number, _sources: BrowserSource[]) =>
      Promise.resolve(opened(_revision)),
  );
  readonly completion = vi.fn(
    async (
      _position: BrowserLanguagePosition,
    ): Promise<BrowserCompletionResult> => ({ items: [] }),
  );
  readonly hover = vi.fn(
    async (
      _position: BrowserLanguagePosition,
    ): Promise<BrowserHoverResult> => ({ hover: null }),
  );
  readonly definition = vi.fn(
    async (
      _position: BrowserLanguagePosition,
    ): Promise<BrowserDefinitionResult> => ({ location: null }),
  );
  readonly references = vi.fn(
    async (
      _position: BrowserLanguagePosition,
      _includeDeclaration: boolean,
    ): Promise<BrowserReferencesResult> => ({ locations: [] }),
  );
  readonly prepareRename = vi.fn(
    async (
      _position: BrowserLanguagePosition,
    ): Promise<BrowserPreparedRenameResult> => ({ prepared: null }),
  );
  readonly rename = vi.fn(
    async (
      _position: BrowserLanguagePosition,
      _newName: string,
    ): Promise<BrowserRenameResult> => ({ edit: { edits: [] } }),
  );
  readonly graph = vi.fn(
    async (
      _workspaceRevision: number,
      _mode: string,
    ): Promise<BrowserGraphResult> => ({
      workspace_revision: _workspaceRevision,
      mode: _mode as 'domain' | 'entity',
      graph: { schema_version: 1, nodes: [], edges: [] },
    }),
  );
  readonly lineage = vi.fn(
    async (_workspaceRevision: number) => ({
      workspace_revision: _workspaceRevision,
      projections: [],
    }),
  );
  readonly compatibility = vi.fn(
    async (_workspaceRevision: number) => ({
      workspace_revision: _workspaceRevision,
      reports: [],
      impacts: [],
    }),
  );
  readonly governance = vi.fn(
    async (_workspaceRevision: number) => ({
      workspace_revision: _workspaceRevision,
      findings: [],
    }),
  );
  readonly formatSource = vi.fn();
  readonly compileJsonSchema = vi.fn();
  readonly dispose = vi.fn();
}

describe('BrowserLanguageServiceController', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('debounces for 300ms and coalesces to the newest workspace', async () => {
    const client = new FakeClient();
    const controller = new BrowserLanguageServiceController(client);

    controller.observe(workspaceAt(2));
    controller.observe(workspaceAt(3));
    await vi.advanceTimersByTimeAsync(299);
    expect(client.openWorkspace).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(client.openWorkspace).toHaveBeenCalledTimes(1);
    expect(client.openWorkspace).toHaveBeenCalledWith(3, sourcesAt(3));
  });

  test('allows one synchronization in flight and then opens the newest workspace', async () => {
    const client = new FakeClient();
    const first = deferred<BrowserWorkspaceResult>();
    client.openWorkspace.mockImplementationOnce(() => first.promise);
    const controller = new BrowserLanguageServiceController(client);

    controller.observe(workspaceAt(2));
    await vi.advanceTimersByTimeAsync(300);
    controller.observe(workspaceAt(3));
    await vi.advanceTimersByTimeAsync(300);
    expect(client.openWorkspace).toHaveBeenCalledTimes(1);

    first.resolve(opened(2));
    await vi.runAllTimersAsync();
    await Promise.resolve();
    expect(client.openWorkspace).toHaveBeenCalledTimes(2);
    expect(client.openWorkspace).toHaveBeenLastCalledWith(3, sourcesAt(3));
  });

  test('provider requests force synchronization before the debounce expires', async () => {
    const client = new FakeClient();
    const synchronization = deferred<BrowserWorkspaceResult>();
    client.openWorkspace.mockImplementationOnce(() => synchronization.promise);
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(4);

    controller.observe(captured);
    const result = controller.completion(captured, 'file:///main.mdl', {
      line: 1,
      character: 2,
    });
    await Promise.resolve();
    expect(client.openWorkspace).toHaveBeenCalledWith(4, sourcesAt(4));
    expect(client.completion).not.toHaveBeenCalled();

    synchronization.resolve(opened(4));
    await expect(result).resolves.toEqual({ items: [] });
    expect(client.completion).toHaveBeenCalledWith({
      workspaceRevision: 4,
      uri: 'file:///main.mdl',
      line: 1,
      character: 2,
    });
  });

  test('publishes diagnostics only for the exact observed revision', async () => {
    const client = new FakeClient();
    const first = deferred<BrowserWorkspaceResult>();
    client.openWorkspace.mockImplementationOnce(() => first.promise);
    const onDiagnostics = vi.fn();
    const controller = new BrowserLanguageServiceController(client, {
      onDiagnostics,
    });
    const diagnostic: BrowserDiagnostic = {
      code: 'parse',
      severity: 'error',
      message: 'Invalid syntax',
      uri: 'file:///main.mdl',
      line: 0,
      column: 0,
      end_line: 0,
      end_column: 1,
    };

    controller.observe(workspaceAt(2));
    await vi.advanceTimersByTimeAsync(300);
    controller.observe(workspaceAt(3));
    first.resolve(opened(2, [diagnostic]));
    await Promise.resolve();
    expect(onDiagnostics).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(300);
    await Promise.resolve();
    expect(onDiagnostics).toHaveBeenCalledWith(3, []);
  });

  test('suppresses failures from synchronization superseded by a newer revision', async () => {
    const client = new FakeClient();
    const first = deferred<BrowserWorkspaceResult>();
    client.openWorkspace.mockImplementationOnce(() => first.promise);
    const onError = vi.fn();
    const controller = new BrowserLanguageServiceController(client, {
      onError,
    });
    controller.observe(workspaceAt(2));
    const synchronization = controller.synchronize();

    controller.observe(workspaceAt(3));
    first.reject(
      new BrowserCompilerError(
        'LANGUAGE_UNAVAILABLE',
        'Language services unavailable',
      ),
    );
    await synchronization;

    expect(onError).not.toHaveBeenCalled();
  });

  test('suppresses provider results after a newer workspace is observed', async () => {
    const client = new FakeClient();
    const completion = deferred<BrowserCompletionResult>();
    client.completion.mockImplementationOnce(() => completion.promise);
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(2);
    controller.observe(captured);

    const result = controller.completion(
      captured,
      'file:///main.mdl',
      { line: 0, character: 0 },
    );
    await Promise.resolve();
    await Promise.resolve();
    controller.observe(workspaceAt(3));
    completion.resolve({ items: [] });

    await expect(result).resolves.toBeUndefined();
  });

  test('synchronizes hover against the captured exact revision', async () => {
    const client = new FakeClient();
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(5);
    controller.observe(captured);

    await expect(
      controller.hover(captured, 'file:///main.mdl', {
        line: 2,
        character: 3,
      }),
    ).resolves.toEqual({ hover: null });
    expect(client.hover).toHaveBeenCalledWith({
      workspaceRevision: 5,
      uri: 'file:///main.mdl',
      line: 2,
      character: 3,
    });
  });

  test('synchronizes definition against the captured exact revision', async () => {
    const client = new FakeClient();
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(5);
    controller.observe(captured);

    await expect(
      controller.definition(captured, 'file:///main.mdl', {
        line: 2,
        character: 3,
      }),
    ).resolves.toEqual({ location: null });
    expect(client.definition).toHaveBeenCalledWith({
      workspaceRevision: 5,
      uri: 'file:///main.mdl',
      line: 2,
      character: 3,
    });
  });

  test('synchronizes references with includeDeclaration', async () => {
    const client = new FakeClient();
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(5);
    controller.observe(captured);

    await expect(
      controller.references(captured, 'file:///main.mdl', {
        line: 2,
        character: 3,
      }, true),
    ).resolves.toEqual({ locations: [] });
    expect(client.references).toHaveBeenCalledWith(
      {
        workspaceRevision: 5,
        uri: 'file:///main.mdl',
        line: 2,
        character: 3,
      },
      true,
    );
  });

  test('synchronizes prepareRename against the captured exact revision', async () => {
    const client = new FakeClient();
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(5);
    controller.observe(captured);

    await expect(
      controller.prepareRename(captured, 'file:///main.mdl', {
        line: 2,
        character: 3,
      }),
    ).resolves.toEqual({ prepared: null });
    expect(client.prepareRename).toHaveBeenCalledWith({
      workspaceRevision: 5,
      uri: 'file:///main.mdl',
      line: 2,
      character: 3,
    });
  });

  test('synchronizes rename with newName', async () => {
    const client = new FakeClient();
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(5);
    controller.observe(captured);

    await expect(
      controller.rename(captured, 'file:///main.mdl', {
        line: 2,
        character: 3,
      }, 'Client'),
    ).resolves.toEqual({ edit: { edits: [] } });
    expect(client.rename).toHaveBeenCalledWith(
      {
        workspaceRevision: 5,
        uri: 'file:///main.mdl',
        line: 2,
        character: 3,
      },
      'Client',
    );
  });

  test('suppresses a completion success that arrives after disposal', async () => {
    const client = new FakeClient();
    const completion = deferred<BrowserCompletionResult>();
    client.completion.mockImplementationOnce(() => completion.promise);
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(2);
    controller.observe(captured);
    await controller.synchronize();

    const result = controller.completion(
      captured,
      'file:///main.mdl',
      { line: 0, character: 0 },
    );
    await Promise.resolve();
    controller.dispose();
    completion.resolve({ items: [] });

    await expect(result).resolves.toBeUndefined();
  });

  test('suppresses a hover success that arrives after disposal', async () => {
    const client = new FakeClient();
    const hover = deferred<BrowserHoverResult>();
    client.hover.mockImplementationOnce(() => hover.promise);
    const controller = new BrowserLanguageServiceController(client);
    const captured = workspaceAt(2);
    controller.observe(captured);
    await controller.synchronize();

    const result = controller.hover(
      captured,
      'file:///main.mdl',
      { line: 0, character: 0 },
    );
    await Promise.resolve();
    controller.dispose();
    hover.resolve({ hover: null });

    await expect(result).resolves.toBeUndefined();
  });

  test.each(['completion', 'hover'] as const)(
    'suppresses terminal %s errors that arrive after disposal',
    async (method) => {
      const client = new FakeClient();
      const provider = deferred<never>();
      client[method].mockImplementationOnce(() => provider.promise);
      const onError = vi.fn();
      const controller = new BrowserLanguageServiceController(client, {
        onError,
      });
      const captured = workspaceAt(2);
      controller.observe(captured);
      await controller.synchronize();

      const result = controller[method](
        captured,
        'file:///main.mdl',
        { line: 0, character: 0 },
      );
      await Promise.resolve();
      controller.dispose();
      provider.reject(
        new BrowserCompilerError('COMPILER_FAILED', 'Worker failed'),
      );

      await expect(result).resolves.toBeUndefined();
      expect(onError).not.toHaveBeenCalled();
    },
  );

  test('silently suppresses stale synchronization and provider errors', async () => {
    const client = new FakeClient();
    client.openWorkspace.mockRejectedValueOnce(
      new BrowserCompilerError('STALE_WORKSPACE', 'stale'),
    );
    const onError = vi.fn();
    const controller = new BrowserLanguageServiceController(client, {
      onError,
    });
    const captured = workspaceAt(2);
    controller.observe(captured);

    await expect(controller.synchronize()).resolves.toBeUndefined();
    client.openWorkspace.mockResolvedValueOnce(opened(2));
    client.completion.mockRejectedValueOnce(
      new BrowserCompilerError('STALE_WORKSPACE', 'stale'),
    );
    await expect(
      controller.completion(captured, 'file:///main.mdl', {
        line: 0,
        character: 0,
      }),
    ).resolves.toBeUndefined();
    expect(onError).not.toHaveBeenCalled();
  });

  test('retry clears a recoverable sync failure and uses the same client', async () => {
    const client = new FakeClient();
    client.openWorkspace
      .mockRejectedValueOnce(
        new BrowserCompilerError('LANGUAGE_UNAVAILABLE', 'unavailable'),
      )
      .mockResolvedValueOnce(opened(2));
    const onError = vi.fn();
    const controller = new BrowserLanguageServiceController(client, {
      onError,
    });
    controller.observe(workspaceAt(2));

    await controller.synchronize();
    expect(onError).toHaveBeenCalledTimes(1);
    await controller.retry();
    expect(client.openWorkspace).toHaveBeenCalledTimes(2);
    expect(client.dispose).not.toHaveBeenCalled();
  });

  test.each([
    'INITIALIZATION_FAILED',
    'COMPILER_FAILED',
    'UNSUPPORTED_PROTOCOL',
  ] as const)(
    'reports terminal %s failures and does not reuse that client on retry',
    async (code) => {
      const client = new FakeClient();
      const terminal = new BrowserCompilerError(
        code,
        'Compiler client is terminal',
      );
      client.openWorkspace.mockRejectedValue(terminal);
      const onError = vi.fn();
      const controller = new BrowserLanguageServiceController(client, {
        onError,
      });
      controller.observe(workspaceAt(2));

      await controller.synchronize();
      await controller.retry();
      expect(client.openWorkspace).toHaveBeenCalledTimes(1);
      expect(onError).toHaveBeenNthCalledWith(1, terminal);
    },
  );

  test('dispose cancels synchronization and disposes the shared client once', async () => {
    const client = new FakeClient();
    const controller = new BrowserLanguageServiceController(client);
    controller.observe(workspaceAt(2));

    controller.dispose();
    controller.dispose();
    await vi.runAllTimersAsync();

    expect(client.openWorkspace).not.toHaveBeenCalled();
    expect(client.dispose).toHaveBeenCalledTimes(1);
    await expect(controller.retry()).resolves.toBeUndefined();
  });

  test('dispose suppresses callbacks from synchronization already in flight', async () => {
    const client = new FakeClient();
    const synchronization = deferred<BrowserWorkspaceResult>();
    client.openWorkspace.mockImplementationOnce(() => synchronization.promise);
    const onDiagnostics = vi.fn();
    const onError = vi.fn();
    const controller = new BrowserLanguageServiceController(client, {
      onDiagnostics,
      onError,
    });
    controller.observe(workspaceAt(2));
    const pending = controller.synchronize();

    controller.dispose();
    synchronization.resolve(opened(2));
    await pending;

    expect(onDiagnostics).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });
});
