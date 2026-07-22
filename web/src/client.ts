import {
  BROWSER_COMPILER_PROTOCOL_VERSION,
  type BrowserCompileResult,
  type BrowserCompatibilityResult,
  type BrowserCompletionResult,
  type BrowserCompilerErrorCode,
  type BrowserCompilerMethod,
  type BrowserCompilerRequest,
  type BrowserDefinitionResult,
  type BrowserFormatResult,
  type BrowserGovernanceResult,
  type BrowserGraphMode,
  type BrowserGraphResult,
  type BrowserHoverResult,
  type BrowserLanguagePosition,
  type BrowserLineageResult,
  type BrowserPreparedRenameResult,
  type BrowserReferencesResult,
  type BrowserRenameResult,
  type BrowserResultGuard,
  type BrowserSource,
  type BrowserWorkspaceResult,
  isBrowserCompileResult,
  isBrowserCompatibilityResult,
  isBrowserCompletionResult,
  isBrowserCompilerResponse,
  isBrowserDefinitionResult,
  isBrowserFormatResult,
  isBrowserGovernanceResult,
  isBrowserGraphResult,
  isBrowserHoverResult,
  isBrowserLineageResult,
  isBrowserPreparedRenameResult,
  isBrowserReferencesResult,
  isBrowserRenameResult,
  isBrowserWorkspaceResult,
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
  guard: BrowserResultGuard<unknown>;
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
    if (event.data.ok) {
      if (!pending.guard(event.data.result)) {
        this.transitionToTerminal(
          new BrowserCompilerError(
            'COMPILER_FAILED',
            'Compiler worker returned an invalid result',
          ),
        );
        return;
      }
      this.pending.delete(event.data.id);
      pending.resolve(event.data.result);
    } else {
      this.pending.delete(event.data.id);
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
        (result): result is null => result === null,
      ).then(() => undefined);
    }
    return this.initializationPromise;
  }

  async openWorkspace(
    workspaceRevision: number,
    sources: BrowserSource[],
  ): Promise<BrowserWorkspaceResult> {
    return this.initializedRequest(
      'workspace.open',
      { workspaceRevision, sources },
      isBrowserWorkspaceResult,
    );
  }

  async formatSource(source: BrowserSource): Promise<BrowserFormatResult> {
    return this.initializedRequest(
      'source.format',
      { source },
      isBrowserFormatResult,
    );
  }

  async compileJsonSchema(
    sources: BrowserSource[],
  ): Promise<BrowserCompileResult> {
    return this.initializedRequest(
      'compile.jsonSchema',
      { sources },
      isBrowserCompileResult,
    );
  }

  completion(
    position: BrowserLanguagePosition,
  ): Promise<BrowserCompletionResult> {
    return this.initializedRequest(
      'language.completion',
      languagePositionPayload(position),
      isBrowserCompletionResult,
    );
  }

  hover(position: BrowserLanguagePosition): Promise<BrowserHoverResult> {
    return this.initializedRequest(
      'language.hover',
      languagePositionPayload(position),
      isBrowserHoverResult,
    );
  }

  definition(
    position: BrowserLanguagePosition,
  ): Promise<BrowserDefinitionResult> {
    return this.initializedRequest(
      'language.definition',
      languagePositionPayload(position),
      isBrowserDefinitionResult,
    );
  }

  references(
    position: BrowserLanguagePosition,
    includeDeclaration: boolean,
  ): Promise<BrowserReferencesResult> {
    return this.initializedRequest(
      'language.references',
      { ...languagePositionPayload(position), includeDeclaration },
      isBrowserReferencesResult,
    );
  }

  prepareRename(
    position: BrowserLanguagePosition,
  ): Promise<BrowserPreparedRenameResult> {
    return this.initializedRequest(
      'language.prepareRename',
      languagePositionPayload(position),
      isBrowserPreparedRenameResult,
    );
  }

  rename(
    position: BrowserLanguagePosition,
    newName: string,
  ): Promise<BrowserRenameResult> {
    return this.initializedRequest(
      'language.rename',
      { ...languagePositionPayload(position), newName },
      isBrowserRenameResult,
    );
  }

  graph(
    workspaceRevision: number,
    mode: BrowserGraphMode,
  ): Promise<BrowserGraphResult> {
    return this.initializedRequest(
      'workspace.graph',
      { workspaceRevision, mode },
      isBrowserGraphResult,
    );
  }

  lineage(workspaceRevision: number): Promise<BrowserLineageResult> {
    return this.initializedRequest(
      'workspace.lineage',
      { workspaceRevision },
      isBrowserLineageResult,
    );
  }

  compatibility(
    workspaceRevision: number,
  ): Promise<BrowserCompatibilityResult> {
    return this.initializedRequest(
      'workspace.compatibility',
      { workspaceRevision },
      isBrowserCompatibilityResult,
    );
  }

  governance(workspaceRevision: number): Promise<BrowserGovernanceResult> {
    return this.initializedRequest(
      'workspace.governance',
      { workspaceRevision },
      isBrowserGovernanceResult,
    );
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
    guard: BrowserResultGuard<T>,
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
        guard: guard as BrowserResultGuard<unknown>,
      });
      this.worker.postMessage(request);
    });
  }

  private async initializedRequest<T>(
    method: BrowserCompilerMethod,
    payload: unknown,
    guard: BrowserResultGuard<T>,
  ): Promise<T> {
    await this.initialize();
    return this.request(method, payload, guard);
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
  | 'completion'
  | 'hover'
  | 'definition'
  | 'references'
  | 'prepareRename'
  | 'rename'
  | 'graph'
  | 'lineage'
  | 'compatibility'
  | 'governance'
  | 'dispose'
>;

function languagePositionPayload(
  position: BrowserLanguagePosition,
): BrowserLanguagePosition {
  return {
    workspaceRevision: position.workspaceRevision,
    uri: position.uri,
    line: position.line,
    character: position.character,
  };
}
