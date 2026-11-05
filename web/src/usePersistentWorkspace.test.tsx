// @vitest-environment jsdom

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { mutateWorkspace, createDefaultWorkspace } from './workspace';
import type {
  WorkspaceLoadResult,
  WorkspaceRepository,
  WorkspaceSaveResult,
} from './workspace-repository';
import { usePersistentWorkspace } from './usePersistentWorkspace';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function deferredRepository() {
  const loadRequest = deferred<WorkspaceLoadResult>();
  const saveRequests: ReturnType<typeof deferred<WorkspaceSaveResult>>[] = [];
  const repository: WorkspaceRepository = {
    load: vi.fn(() => loadRequest.promise),
    save: vi.fn(() => {
      const request = deferred<WorkspaceSaveResult>();
      saveRequests.push(request);
      return request.promise;
    }),
    remove: vi.fn(async () => undefined),
  };
  return { repository, loadRequest, saveRequests };
}

const defaultWorkspace = createDefaultWorkspace('domain default {}');
const restoredWorkspace = mutateWorkspace(defaultWorkspace, {
  type: 'update',
  path: 'main.mdl',
  content: 'domain restored {}',
});

afterEach(() => {
  vi.useRealTimers();
});

test('restores before exposing a stored workspace', async () => {
  const { repository, loadRequest } = deferredRepository();
  const { result } = renderHook(() =>
    usePersistentWorkspace({
      repository,
      defaultWorkspace,
      debounceMs: 10,
    }),
  );
  expect(result.current.phase).toBe('restoring');

  loadRequest.resolve({ status: 'ready', workspace: restoredWorkspace });
  await waitFor(() => expect(result.current.phase).toBe('saved'));
  expect(result.current.workspace).toEqual(restoredWorkspace);
  expect(repository.save).not.toHaveBeenCalled();
});

test('an older save completion cannot mark newer state saved', async () => {
  vi.useFakeTimers();
  const { repository, loadRequest, saveRequests } = deferredRepository();
  const { result } = renderHook(() =>
    usePersistentWorkspace({
      repository,
      defaultWorkspace,
      debounceMs: 10,
    }),
  );
  loadRequest.resolve({ status: 'ready', workspace: defaultWorkspace });
  await act(async () => Promise.resolve());

  const revision2 = mutateWorkspace(defaultWorkspace, {
    type: 'update',
    path: 'main.mdl',
    content: 'domain two {}',
  });
  const revision3 = mutateWorkspace(revision2, {
    type: 'update',
    path: 'main.mdl',
    content: 'domain three {}',
  });
  act(() => result.current.replace(revision2));
  await act(() => vi.advanceTimersByTimeAsync(10));
  act(() => result.current.replace(revision3));
  await act(() => vi.advanceTimersByTimeAsync(10));

  saveRequests[0]!.resolve('saved');
  await act(async () => Promise.resolve());
  expect(result.current.phase).toBe('saving');
  saveRequests[1]!.resolve('saved');
  await act(async () => Promise.resolve());
  expect(result.current.phase).toBe('saved');
});

test('keeps invalid storage recoverable until reset', async () => {
  const raw = { schemaVersion: 99, source: '<script>x</script>' };
  const repository: WorkspaceRepository = {
    load: vi.fn(async (): Promise<WorkspaceLoadResult> => ({
      status: 'recovery-required',
      reason: 'incompatible',
      raw,
    })),
    save: vi.fn(async (): Promise<WorkspaceSaveResult> => 'saved'),
    remove: vi.fn(async () => undefined),
  };
  const { result } = renderHook(() =>
    usePersistentWorkspace({ repository, defaultWorkspace }),
  );
  await waitFor(() =>
    expect(result.current.phase).toBe('recovery-required'),
  );
  expect(result.current.recovery?.raw).toBe(raw);
  expect(repository.save).not.toHaveBeenCalled();

  await act(() => result.current.reset());
  expect(repository.remove).toHaveBeenCalledWith('local');
  expect(result.current.workspace).toEqual({
    ...defaultWorkspace,
    revision: 2,
  });
});

test('reset bumps revision forward instead of reverting', async () => {
  const repository: WorkspaceRepository = {
    load: vi.fn(async (): Promise<WorkspaceLoadResult> => ({
      status: 'ready',
      workspace: restoredWorkspace,
    })),
    save: vi.fn(async (): Promise<WorkspaceSaveResult> => 'saved'),
    remove: vi.fn(async () => undefined),
  };
  const { result } = renderHook(() =>
    usePersistentWorkspace({ repository, defaultWorkspace }),
  );
  await waitFor(() => expect(result.current.phase).toBe('saved'));
  const revisionBefore = result.current.workspace.revision;

  await act(() => result.current.reset());

  expect(result.current.workspace.revision).toBe(revisionBefore + 1);
  expect(result.current.workspace.files).toEqual(defaultWorkspace.files);
  expect(result.current.workspace.activeFile).toBe(defaultWorkspace.activeFile);
});

test('retry saves newer in-memory work instead of loading older storage', async () => {
  const edited = mutateWorkspace(defaultWorkspace, {
    type: 'update',
    path: 'main.mdl',
    content: 'domain edited {}',
  });
  const repository: WorkspaceRepository = {
    load: vi.fn().mockRejectedValueOnce(new Error('unavailable')),
    save: vi.fn(async (): Promise<WorkspaceSaveResult> => 'saved'),
    remove: vi.fn(async () => undefined),
  };
  const { result } = renderHook(() =>
    usePersistentWorkspace({ repository, defaultWorkspace }),
  );
  await waitFor(() => expect(result.current.phase).toBe('memory-only'));
  act(() => result.current.replace(edited));

  await act(() => result.current.retry());
  expect(result.current.workspace).toEqual(edited);
  expect(repository.save).toHaveBeenCalledWith(edited);
  expect(repository.load).toHaveBeenCalledTimes(1);
});

test('a stale save result is not reported as saved', async () => {
  const edited = mutateWorkspace(defaultWorkspace, {
    type: 'update',
    path: 'main.mdl',
    content: 'domain edited {}',
  });
  const repository: WorkspaceRepository = {
    load: vi.fn(async (): Promise<WorkspaceLoadResult> => ({
      status: 'ready',
      workspace: defaultWorkspace,
    })),
    save: vi.fn(async (): Promise<WorkspaceSaveResult> => 'stale'),
    remove: vi.fn(async () => undefined),
  };
  const { result } = renderHook(() =>
    usePersistentWorkspace({ repository, defaultWorkspace, debounceMs: 1 }),
  );
  await waitFor(() => expect(result.current.phase).toBe('saved'));

  act(() => result.current.replace(edited, { immediate: true }));

  await waitFor(() => expect(result.current.phase).toBe('memory-only'));
  expect(result.current.workspace).toEqual(edited);
});

class FakeChannel {
  static instances: FakeChannel[] = [];
  onmessage: ((event: { data: unknown }) => void) | null = null;
  posted: unknown[] = [];
  constructor(public name: string) {
    FakeChannel.instances.push(this);
  }
  postMessage(data: unknown): void {
    this.posted.push(data);
  }
  close(): void {
    FakeChannel.instances = FakeChannel.instances.filter((c) => c !== this);
  }
}

function channelRepository(stored: () => WorkspaceLoadResult) {
  const repository: WorkspaceRepository = {
    load: vi.fn(async () => stored()),
    save: vi.fn(async (): Promise<WorkspaceSaveResult> => 'saved'),
    remove: vi.fn(async () => undefined),
  };
  return repository;
}

test('announces saved revisions to other tabs', async () => {
  FakeChannel.instances = [];
  vi.stubGlobal('BroadcastChannel', FakeChannel);
  try {
    const repository = channelRepository(() => ({
      status: 'ready',
      workspace: defaultWorkspace,
    }));
    const { result } = renderHook(() =>
      usePersistentWorkspace({ repository, defaultWorkspace, debounceMs: 1 }),
    );
    await waitFor(() => expect(result.current.phase).toBe('saved'));
    act(() => result.current.replace(restoredWorkspace, { immediate: true }));
    await waitFor(() => expect(result.current.phase).toBe('saved'));
    expect(FakeChannel.instances[0]?.posted).toContainEqual({
      id: defaultWorkspace.id,
      revision: restoredWorkspace.revision,
    });
  } finally {
    vi.unstubAllGlobals();
  }
});

test('a clean tab reloads when another tab saves a newer revision', async () => {
  FakeChannel.instances = [];
  vi.stubGlobal('BroadcastChannel', FakeChannel);
  try {
    let stored: WorkspaceLoadResult = {
      status: 'ready',
      workspace: defaultWorkspace,
    };
    const repository = channelRepository(() => stored);
    const { result } = renderHook(() =>
      usePersistentWorkspace({ repository, defaultWorkspace, debounceMs: 1 }),
    );
    await waitFor(() => expect(result.current.phase).toBe('saved'));
    stored = { status: 'ready', workspace: restoredWorkspace };

    act(() =>
      FakeChannel.instances[0]?.onmessage?.({
        data: { id: defaultWorkspace.id, revision: restoredWorkspace.revision },
      }),
    );

    await waitFor(() => expect(result.current.workspace).toEqual(restoredWorkspace));
    expect(result.current.phase).toBe('saved');
  } finally {
    vi.unstubAllGlobals();
  }
});

test('a dirty tab is flagged memory-only when another tab saves newer', async () => {
  FakeChannel.instances = [];
  vi.stubGlobal('BroadcastChannel', FakeChannel);
  try {
    const repository = channelRepository(() => ({
      status: 'ready',
      workspace: defaultWorkspace,
    }));
    const { result } = renderHook(() =>
      usePersistentWorkspace({ repository, defaultWorkspace, debounceMs: 60_000 }),
    );
    await waitFor(() => expect(result.current.phase).toBe('saved'));
    const edited = mutateWorkspace(defaultWorkspace, {
      type: 'update',
      path: 'main.mdl',
      content: 'domain local {}',
    });
    act(() => result.current.replace(edited));

    act(() =>
      FakeChannel.instances[0]?.onmessage?.({
        data: { id: defaultWorkspace.id, revision: edited.revision + 5 },
      }),
    );

    expect(result.current.phase).toBe('memory-only');
    expect(result.current.workspace).toEqual(edited);
  } finally {
    vi.unstubAllGlobals();
  }
});
