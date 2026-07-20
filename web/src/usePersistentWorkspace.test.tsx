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
  expect(result.current.workspace).toEqual(defaultWorkspace);
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
