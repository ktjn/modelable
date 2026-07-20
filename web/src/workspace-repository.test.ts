import { IDBFactory } from 'fake-indexeddb';
import { beforeEach, expect, test } from 'vitest';

import { createDefaultWorkspace, mutateWorkspace } from './workspace';
import { IndexedDbWorkspaceRepository } from './workspace-repository';

let repository: IndexedDbWorkspaceRepository;
let factory: IDBFactory;
let databaseName: string;

beforeEach(() => {
  factory = new IDBFactory();
  databaseName = `test-${crypto.randomUUID()}`;
  repository = new IndexedDbWorkspaceRepository(factory, databaseName);
});

test('round-trips a valid multi-file workspace', async () => {
  const workspace = mutateWorkspace(
    createDefaultWorkspace('domain demo {}'),
    {
      type: 'create',
      path: 'customer/customer.mdl',
      content: 'domain customer {}',
    },
  );

  await expect(repository.save(workspace)).resolves.toBe('saved');
  await expect(repository.load('local')).resolves.toEqual({
    status: 'ready',
    workspace,
  });
});

test('removes only the requested workspace', async () => {
  const workspace = createDefaultWorkspace('domain demo {}');
  await repository.save(workspace);
  await repository.remove('local');
  await expect(repository.load('local')).resolves.toEqual({
    status: 'missing',
  });
});

test('a stale revision cannot overwrite a newer workspace', async () => {
  const initial = createDefaultWorkspace('domain demo {}');
  const newer = mutateWorkspace(initial, {
    type: 'update',
    path: 'main.mdl',
    content: 'domain newer {}',
  });

  await repository.save(newer);
  await expect(repository.save(initial)).resolves.toBe('stale');
  await expect(repository.load('local')).resolves.toEqual({
    status: 'ready',
    workspace: newer,
  });
});

test('returns invalid raw state without overwriting it', async () => {
  await putRawRecord({
    id: 'local',
    schemaVersion: 1,
    revision: 2,
    files: [{ path: '../escape.mdl', content: 'secret', version: 1 }],
    activeFile: '../escape.mdl',
  });

  const result = await repository.load('local');
  expect(result).toMatchObject({
    status: 'recovery-required',
    reason: 'invalid',
  });
  expect(await readRawRecord('local')).toEqual(
    result.status === 'recovery-required' ? result.raw : undefined,
  );
});

async function putRawRecord(value: unknown): Promise<void> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction('workspaces', 'readwrite');
    const complete = transactionCompletion(transaction);
    transaction.objectStore('workspaces').put(value);
    await complete;
  } finally {
    database.close();
  }
}

async function readRawRecord(id: string): Promise<unknown> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction('workspaces', 'readonly');
    const complete = transactionCompletion(transaction);
    const request = transaction.objectStore('workspaces').get(id);
    const value = await requestValue(request);
    await complete;
    return value;
  } finally {
    database.close();
  }
}

function openDatabase(): Promise<IDBDatabase> {
  const request = factory.open(databaseName, 1);
  request.onupgradeneeded = () => {
    request.result.createObjectStore('workspaces', { keyPath: 'id' });
  };
  return requestValue(request);
}

function requestValue<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionCompletion(
  transaction: IDBTransaction,
): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error);
    transaction.onerror = () => reject(transaction.error);
  });
}
