import {
  WorkspaceValidationError,
  parseWorkspaceRecord,
  type PlaygroundWorkspace,
} from './workspace';

export type WorkspaceLoadResult =
  | { status: 'missing' }
  | { status: 'ready'; workspace: PlaygroundWorkspace }
  | {
      status: 'recovery-required';
      reason: 'invalid' | 'incompatible';
      raw: unknown;
    };

export type WorkspaceSaveResult = 'saved' | 'stale';

export interface WorkspaceRepository {
  load(id: string): Promise<WorkspaceLoadResult>;
  save(workspace: PlaygroundWorkspace): Promise<WorkspaceSaveResult>;
  remove(id: string): Promise<void>;
}

const DATABASE_VERSION = 1;
const WORKSPACES_STORE = 'workspaces';

export class IndexedDbWorkspaceRepository implements WorkspaceRepository {
  readonly #factory: IDBFactory;
  readonly #databaseName: string;

  constructor(
    factory: IDBFactory = indexedDB,
    databaseName = 'modelable-playground',
  ) {
    this.#factory = factory;
    this.#databaseName = databaseName;
  }

  async load(id: string): Promise<WorkspaceLoadResult> {
    const database = await this.#open();
    try {
      const transaction = database.transaction(WORKSPACES_STORE, 'readonly');
      const complete = transactionComplete(transaction);
      const raw = await requestResult(
        transaction.objectStore(WORKSPACES_STORE).get(id),
      );
      await complete;
      if (raw === undefined) {
        return { status: 'missing' };
      }
      try {
        return { status: 'ready', workspace: parseWorkspaceRecord(raw) };
      } catch (error) {
        if (error instanceof WorkspaceValidationError) {
          return {
            status: 'recovery-required',
            reason: error.reason,
            raw,
          };
        }
        throw error;
      }
    } finally {
      database.close();
    }
  }

  async save(
    workspace: PlaygroundWorkspace,
  ): Promise<WorkspaceSaveResult> {
    const database = await this.#open();
    try {
      const transaction = database.transaction(WORKSPACES_STORE, 'readwrite');
      const complete = transactionComplete(transaction);
      const store = transaction.objectStore(WORKSPACES_STORE);
      const current = await requestResult<unknown>(store.get(workspace.id));
      if (
        typeof current === 'object' &&
        current !== null &&
        'revision' in current &&
        typeof current.revision === 'number' &&
        current.revision > workspace.revision
      ) {
        await complete;
        return 'stale';
      }
      await requestResult(
        store.put(structuredClone(workspace)),
      );
      await complete;
      return 'saved';
    } finally {
      database.close();
    }
  }

  async remove(id: string): Promise<void> {
    const database = await this.#open();
    try {
      const transaction = database.transaction(WORKSPACES_STORE, 'readwrite');
      const complete = transactionComplete(transaction);
      await requestResult(
        transaction.objectStore(WORKSPACES_STORE).delete(id),
      );
      await complete;
    } finally {
      database.close();
    }
  }

  #open(): Promise<IDBDatabase> {
    const request = this.#factory.open(this.#databaseName, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(WORKSPACES_STORE)) {
        database.createObjectStore(WORKSPACES_STORE, { keyPath: 'id' });
      }
    };
    return requestResult(request);
  }
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionComplete(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () =>
      reject(transaction.error ?? new Error('IndexedDB transaction aborted'));
    transaction.onerror = () =>
      reject(transaction.error ?? new Error('IndexedDB transaction failed'));
  });
}
