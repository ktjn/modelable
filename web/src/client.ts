import {
  BROWSER_COMPILER_PROTOCOL_VERSION,
  type BrowserCompileResult,
  type BrowserCompilerErrorCode,
  type BrowserCompilerMethod,
  type BrowserCompilerRequest,
  type BrowserFormatResult,
  type BrowserSource,
  type BrowserWorkspaceResult,
  isBrowserCompilerResponse,
} from './protocol';

export interface WorkerLike {
  postMessage(message: BrowserCompilerRequest): void;
  addEventListener(
    type: 'message',
    listener: (event: MessageEvent<unknown>) => void,
  ): void;
  addEventListener(
    type: 'error',
    listener: (event: ErrorEvent) => void,
  ): void;
  removeEventListener(
    type: 'message',
    listener: (event: MessageEvent<unknown>) => void,
  ): void;
  removeEventListener(
    type: 'error',
    listener: (event: ErrorEvent) => void,
  ): void;
  terminate(): void;
}

interface PendingRequest {
  resolve: (result: unknown) => void;
  reject: (error: BrowserCompilerError) => void;
}

export class BrowserCompilerError extends Error {
  constructor(
    readonly code: BrowserCompilerErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'BrowserCompilerError';
  }
}

export class BrowserCompilerClient {
  private readonly pending = new Map<string, PendingRequest>();
  private initializationPromise: Promise<void> | undefined;
  private terminalError: BrowserCompilerError | undefined;

  private readonly onMessage = (event: MessageEvent<unknown>): void => {
    if (!isBrowserCompilerResponse(event.data)) {
      this.transitionToTerminal(
        new BrowserCompilerError(
          'COMPILER_FAILED',
          'Compiler worker returned an invalid response',
        ),
      );
      return;
    }
    const pending = this.pending.get(event.data.id);
    if (pending === undefined) {
      return;
    }
    this.pending.delete(event.data.id);
    if (event.data.ok) {
      pending.resolve(event.data.result);
    } else {
      pending.reject(
        new BrowserCompilerError(
          event.data.error.code,
          event.data.error.message,
        ),
      );
    }
  };

  private readonly onError = (): void => {
    this.transitionToTerminal(
      new BrowserCompilerError('COMPILER_FAILED', 'Compiler worker failed'),
    );
  };

  constructor(
    private readonly worker: WorkerLike = new Worker(
      new URL('./compiler.worker.ts', import.meta.url),
      { type: 'module' },
    ),
  ) {
    worker.addEventListener('message', this.onMessage);
    worker.addEventListener('error', this.onError);
  }

  initialize(): Promise<void> {
    if (this.initializationPromise === undefined) {
      this.initializationPromise = this.request(
        'runtime.initialize',
        {},
      ).then(() => undefined);
    }
    return this.initializationPromise;
  }

  async openWorkspace(
    sources: BrowserSource[],
  ): Promise<BrowserWorkspaceResult> {
    await this.initialize();
    return this.request('workspace.open', { sources });
  }

  async formatSource(source: BrowserSource): Promise<BrowserFormatResult> {
    await this.initialize();
    return this.request('source.format', { source });
  }

  async compileJsonSchema(
    sources: BrowserSource[],
  ): Promise<BrowserCompileResult> {
    await this.initialize();
    return this.request('compile.jsonSchema', { sources });
  }

  dispose(): void {
    this.transitionToTerminal(
      new BrowserCompilerError(
        'COMPILER_FAILED',
        'Compiler client has been disposed',
      ),
    );
  }

  private request<T>(
    method: BrowserCompilerMethod,
    payload: unknown,
  ): Promise<T> {
    const unavailable = this.unavailableError();
    if (unavailable !== undefined) {
      return Promise.reject(unavailable);
    }
    const id = crypto.randomUUID();
    const request: BrowserCompilerRequest = {
      protocolVersion: BROWSER_COMPILER_PROTOCOL_VERSION,
      id,
      method,
      payload,
    };
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, {
        resolve: resolve as (result: unknown) => void,
        reject,
      });
      this.worker.postMessage(request);
    });
  }

  private unavailableError(): BrowserCompilerError | undefined {
    return this.terminalError;
  }

  private transitionToTerminal(error: BrowserCompilerError): void {
    if (this.terminalError !== undefined) {
      return;
    }
    this.terminalError = error;
    this.worker.removeEventListener('message', this.onMessage);
    this.worker.removeEventListener('error', this.onError);
    this.worker.terminate();
    for (const pending of this.pending.values()) {
      pending.reject(error);
    }
    this.pending.clear();
  }
}

export type BrowserCompilerClientLike = Pick<
  BrowserCompilerClient,
  | 'initialize'
  | 'openWorkspace'
  | 'formatSource'
  | 'compileJsonSchema'
  | 'dispose'
>;
