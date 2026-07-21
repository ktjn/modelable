import {
  BrowserCompilerError,
  type BrowserCompilerClientLike,
} from '../client';
import type {
  BrowserCompletionResult,
  BrowserDefinitionResult,
  BrowserDiagnostic,
  BrowserHoverResult,
  BrowserLanguagePositionValue,
  BrowserPreparedRenameResult,
  BrowserReferencesResult,
  BrowserRenameResult,
} from '../protocol';
import {
  type PlaygroundWorkspace,
  workspaceSources,
} from '../workspace';

export interface BrowserLanguageServiceCallbacks {
  onDiagnostics?(
    workspaceRevision: number,
    diagnostics: BrowserDiagnostic[],
  ): void;
  onError?(error: BrowserCompilerError): void;
}

export class BrowserLanguageServiceController {
  private observed: PlaygroundWorkspace | undefined;
  private acceptedRevision = 0;
  private inFlight: Promise<void> | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private lastFailure: BrowserCompilerError | undefined;
  private disposed = false;

  constructor(
    private readonly client: BrowserCompilerClientLike,
    private readonly callbacks: BrowserLanguageServiceCallbacks = {},
  ) {}

  observe(workspace: PlaygroundWorkspace): void {
    if (this.disposed) {
      return;
    }
    this.observed = workspace;
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.synchronize(workspace.revision);
    }, 300);
  }

  async synchronize(
    workspaceRevision = this.observed?.revision,
  ): Promise<void> {
    if (this.disposed || workspaceRevision === undefined) {
      return;
    }
    if (this.observed?.revision === workspaceRevision) {
      this.clearTimer();
    }

    while (
      !this.disposed &&
      this.observed?.revision === workspaceRevision &&
      this.acceptedRevision !== workspaceRevision
    ) {
      if (this.inFlight !== undefined) {
        await this.inFlight;
        continue;
      }

      const workspace = this.observed;
      const synchronization = this.openWorkspace(workspace);
      this.inFlight = synchronization;
      try {
        await synchronization;
      } finally {
        if (this.inFlight === synchronization) {
          this.inFlight = undefined;
        }
      }
      return;
    }
  }

  async completion(
    captured: PlaygroundWorkspace,
    uri: string,
    position: BrowserLanguagePositionValue,
  ): Promise<BrowserCompletionResult | undefined> {
    if (!(await this.ensureRevision(captured))) {
      return undefined;
    }
    try {
      const result = await this.client.completion({
        workspaceRevision: captured.revision,
        uri,
        line: position.line,
        character: position.character,
      });
      return !this.disposed &&
        this.observed?.revision === captured.revision
        ? result
        : undefined;
    } catch (error: unknown) {
      return this.handleProviderError(error, captured.revision);
    }
  }

  async hover(
    captured: PlaygroundWorkspace,
    uri: string,
    position: BrowserLanguagePositionValue,
  ): Promise<BrowserHoverResult | undefined> {
    if (!(await this.ensureRevision(captured))) {
      return undefined;
    }
    try {
      const result = await this.client.hover({
        workspaceRevision: captured.revision,
        uri,
        line: position.line,
        character: position.character,
      });
      return !this.disposed &&
        this.observed?.revision === captured.revision
        ? result
        : undefined;
    } catch (error: unknown) {
      return this.handleProviderError(error, captured.revision);
    }
  }

  async definition(
    captured: PlaygroundWorkspace,
    uri: string,
    position: BrowserLanguagePositionValue,
  ): Promise<BrowserDefinitionResult | undefined> {
    if (!(await this.ensureRevision(captured))) {
      return undefined;
    }
    try {
      const result = await this.client.definition({
        workspaceRevision: captured.revision,
        uri,
        line: position.line,
        character: position.character,
      });
      return !this.disposed &&
        this.observed?.revision === captured.revision
        ? result
        : undefined;
    } catch (error: unknown) {
      return this.handleProviderError(error, captured.revision);
    }
  }

  async references(
    captured: PlaygroundWorkspace,
    uri: string,
    position: BrowserLanguagePositionValue,
    includeDeclaration: boolean,
  ): Promise<BrowserReferencesResult | undefined> {
    if (!(await this.ensureRevision(captured))) {
      return undefined;
    }
    try {
      const result = await this.client.references(
        {
          workspaceRevision: captured.revision,
          uri,
          line: position.line,
          character: position.character,
        },
        includeDeclaration,
      );
      return !this.disposed &&
        this.observed?.revision === captured.revision
        ? result
        : undefined;
    } catch (error: unknown) {
      return this.handleProviderError(error, captured.revision);
    }
  }

  async prepareRename(
    captured: PlaygroundWorkspace,
    uri: string,
    position: BrowserLanguagePositionValue,
  ): Promise<BrowserPreparedRenameResult | undefined> {
    if (!(await this.ensureRevision(captured))) {
      return undefined;
    }
    try {
      const result = await this.client.prepareRename({
        workspaceRevision: captured.revision,
        uri,
        line: position.line,
        character: position.character,
      });
      return !this.disposed &&
        this.observed?.revision === captured.revision
        ? result
        : undefined;
    } catch (error: unknown) {
      return this.handleProviderError(error, captured.revision);
    }
  }

  async rename(
    captured: PlaygroundWorkspace,
    uri: string,
    position: BrowserLanguagePositionValue,
    newName: string,
  ): Promise<BrowserRenameResult | undefined> {
    if (!(await this.ensureRevision(captured))) {
      return undefined;
    }
    try {
      const result = await this.client.rename(
        {
          workspaceRevision: captured.revision,
          uri,
          line: position.line,
          character: position.character,
        },
        newName,
      );
      return !this.disposed &&
        this.observed?.revision === captured.revision
        ? result
        : undefined;
    } catch (error: unknown) {
      return this.handleProviderError(error, captured.revision);
    }
  }

  async retry(): Promise<void> {
    if (
      this.disposed ||
      (this.lastFailure !== undefined &&
        isTerminalError(this.lastFailure))
    ) {
      return;
    }
    this.lastFailure = undefined;
    await this.synchronize();
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.clearTimer();
    this.client.dispose();
  }

  private async ensureRevision(
    captured: PlaygroundWorkspace,
  ): Promise<boolean> {
    if (
      this.disposed ||
      this.observed?.revision !== captured.revision
    ) {
      return false;
    }
    if (this.acceptedRevision !== captured.revision) {
      await this.synchronize(captured.revision);
    }
    return (
      !this.disposed &&
      this.observed?.revision === captured.revision &&
      this.acceptedRevision === captured.revision
    );
  }

  private async openWorkspace(
    workspace: PlaygroundWorkspace,
  ): Promise<void> {
    try {
      const result = await this.client.openWorkspace(
        workspace.revision,
        workspaceSources(workspace),
      );
      if (this.disposed) {
        return;
      }
      if (result.workspace_revision !== workspace.revision) {
        return;
      }
      this.acceptedRevision = result.workspace_revision;
      this.lastFailure = undefined;
      if (this.observed?.revision === result.workspace_revision) {
        this.callbacks.onDiagnostics?.(
          result.workspace_revision,
          result.diagnostics,
        );
      }
    } catch (error: unknown) {
      if (
        this.disposed ||
        this.observed?.revision !== workspace.revision ||
        isStaleError(error)
      ) {
        return;
      }
      const compilerError = toCompilerError(error);
      this.lastFailure = compilerError;
      this.callbacks.onError?.(compilerError);
    }
  }

  private handleProviderError<T>(
    error: unknown,
    workspaceRevision: number,
  ): T | undefined {
    if (
      this.disposed ||
      isStaleError(error) ||
      this.observed?.revision !== workspaceRevision
    ) {
      return undefined;
    }
    const compilerError = toCompilerError(error);
    if (isTerminalError(compilerError)) {
      this.lastFailure = compilerError;
      this.callbacks.onError?.(compilerError);
      return undefined;
    }
    throw compilerError;
  }

  private clearTimer(): void {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
  }
}

function isStaleError(
  error: unknown,
): error is BrowserCompilerError {
  return (
    error instanceof BrowserCompilerError &&
    error.code === 'STALE_WORKSPACE'
  );
}

function isTerminalError(error: BrowserCompilerError): boolean {
  return (
    error.code === 'COMPILER_FAILED' ||
    error.code === 'INITIALIZATION_FAILED' ||
    error.code === 'UNSUPPORTED_PROTOCOL'
  );
}

function toCompilerError(error: unknown): BrowserCompilerError {
  return error instanceof BrowserCompilerError
    ? error
    : new BrowserCompilerError(
        'COMPILER_FAILED',
        'Browser language synchronization failed',
      );
}
