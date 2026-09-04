import {
  BROWSER_COMPILER_PROTOCOL_VERSION,
  type BrowserCompileResult,
  type BrowserConversationReply,
  type BrowserConversationReplyValue,
  type BrowserConversationResult,
  type BrowserCompatibilityResult,
  type BrowserCompletionResult,
  type BrowserCompilerErrorCode,
  type BrowserCompilerMethod,
  type BrowserCompilerRequest,
  type BrowserDefinitionResult,
  type BrowserFacetDocument,
  type BrowserFormatResult,
  type BrowserGovernanceResult,
  type BrowserGraphMode,
  type BrowserGraphResult,
  type BrowserHoverResult,
  type BrowserLanguagePosition,
  type BrowserLineageResult,
  type BrowserPlanResult,
  type BrowserPreparedRenameResult,
  type BrowserQueryRequest,
  type BrowserQueryResult,
  type BrowserReferencesResult,
  type BrowserRenameResult,
  type BrowserResultGuard,
  type BrowserSource,
  type BrowserWorkspaceResult,
  isBrowserCompileResult,
  isBrowserConversationPendingResult,
  isBrowserConversationReply,
  isBrowserConversationResult,
  isBrowserCompatibilityResult,
  isBrowserCompletionResult,
  isBrowserCompilerResponse,
  isBrowserDefinitionResult,
  isBrowserFormatResult,
  isBrowserGovernanceResult,
  isBrowserGraphResult,
  isBrowserHoverResult,
  isBrowserLineageResult,
  isBrowserPlanResult,
  isBrowserPreparedRenameResult,
  isBrowserQueryResult,
  isBrowserReferencesResult,
  isBrowserRenameResult,
  isBrowserWorkspaceResult,
} from './protocol';
import { toErrorMessage } from './errors';
import type { LlmProvider } from './ai/types';

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

export type CompileTarget =
  | 'jsonSchema'
  | 'typescript'
  | 'sql-postgres'
  | 'sql-clickhouse'
  | 'protobuf'
  | 'rust'
  | 'java'
  | 'go'
  | 'csharp'
  | 'markdown'
  | 'python';

/** Human-readable name for each compile target, in menu order. */
export const COMPILE_TARGET_LABELS: Record<CompileTarget, string> = {
  jsonSchema: 'JSON Schema',
  typescript: 'TypeScript',
  'sql-postgres': 'SQL (Postgres)',
  'sql-clickhouse': 'SQL (ClickHouse)',
  protobuf: 'Protobuf',
  rust: 'Rust',
  java: 'Java',
  go: 'Go',
  csharp: 'C#',
  markdown: 'Markdown',
  python: 'Python',
};

export interface ConversationTurnInput {
  sessionId: string;
  workspaceRevision: number;
  message: string;
  activeDocumentUri: string | null;
  position: { line: number; character: number } | null;
  documentationIndexUrl?: string;
  documentationAssetRoot?: string;
  automaticDocumentation?: boolean;
}

export interface ConversationCitation {
  label: string;
  externalId: string;
  url: string;
  title: string;
  heading: string | null;
  score: number;
}

export interface ConversationTurnReplyValue extends BrowserConversationReplyValue {
  retrievalUsed?: boolean;
  citations?: ConversationCitation[];
  routeReason?: string;
}

export interface ConversationTurnReply extends Omit<BrowserConversationReply, 'reply'> {
  reply: ConversationTurnReplyValue;
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
    facetsDocument?: BrowserFacetDocument,
  ): Promise<BrowserWorkspaceResult> {
    return this.initializedRequest(
      'workspace.open',
      {
        workspaceRevision,
        sources,
        ...(facetsDocument === undefined ? {} : { facetsDocument }),
      },
      isBrowserWorkspaceResult,
    );
  }

  query(
    workspaceRevision: number,
    request: BrowserQueryRequest,
  ): Promise<BrowserQueryResult> {
    return this.initializedRequest(
      'workspace.query',
      { workspaceRevision, request },
      isBrowserQueryResult,
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
    return this.compile(sources, 'jsonSchema');
  }

  async compile(
    sources: BrowserSource[],
    target: CompileTarget,
  ): Promise<BrowserCompileResult> {
    return this.initializedRequest(
      'compile',
      { sources, target },
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

  plans(workspaceRevision: number): Promise<BrowserPlanResult> {
    return this.initializedRequest(
      'workspace.plans',
      { workspaceRevision },
      isBrowserPlanResult,
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

  async conversationTurn(
    input: ConversationTurnInput,
    provider: LlmProvider,
    signal?: AbortSignal,
  ): Promise<ConversationTurnReply> {
    let result = await this.initializedRequest<BrowserConversationResult>(
      'conversation.turn',
      {
        sessionId: input.sessionId,
        workspaceRevision: input.workspaceRevision,
        message: input.message,
        activeDocumentUri: input.activeDocumentUri,
        line: input.position?.line ?? null,
        character: input.position?.character ?? null,
        ...(input.documentationIndexUrl === undefined
          ? {}
          : { documentationIndexUrl: input.documentationIndexUrl }),
        ...(input.documentationAssetRoot === undefined
          ? {}
          : { documentationAssetRoot: input.documentationAssetRoot }),
        ...(input.automaticDocumentation === undefined
          ? {}
          : { automaticDocumentation: input.automaticDocumentation }),
      },
      isBrowserConversationResult,
    );
    while (isBrowserConversationPendingResult(result)) {
      const requestId = result.request_id;
      try {
        throwIfConversationAborted(signal);
        const response = await provider.complete({
          system: result.llm_request.system,
          user: result.llm_request.user,
          temperature: result.llm_request.temperature,
          responseFormat: result.llm_request.response_format === 'json' ? 'json' : 'text',
          schema: result.llm_request.schema ?? undefined,
        });
        throwIfConversationAborted(signal);
        result = await this.initializedRequest<BrowserConversationResult>(
          'conversation.resume',
          {
            sessionId: input.sessionId,
            requestId,
            workspaceRevision: input.workspaceRevision,
            llmResponseContent: response.content,
          },
          isBrowserConversationResult,
        );
      } catch (error: unknown) {
        let failureResult: BrowserConversationResult | undefined;
        try {
          failureResult = await this.initializedRequest<BrowserConversationResult>(
            'conversation.fail',
            {
              sessionId: input.sessionId,
              requestId,
              workspaceRevision: input.workspaceRevision,
              error: toErrorMessage(error, 'Provider completion failed'),
            },
            isBrowserConversationResult,
          );
        } catch {
          // Preserve the provider/cancellation failure that caused cleanup.
        }
        if (
          failureResult !== undefined &&
          isBrowserConversationPendingResult(failureResult)
        ) {
          result = failureResult;
          continue;
        }
        throw error;
      }
    }
    return normalizeConversationTurnReply(result);
  }

  conversationApply(
    sessionId: string,
    actionId: string,
    workspaceRevision: number,
  ): Promise<BrowserConversationReply> {
    return this.initializedRequest(
      'conversation.apply',
      { sessionId, actionId, workspaceRevision },
      isBrowserConversationReply,
    );
  }

  conversationDiscard(
    sessionId: string,
    actionId: string,
    workspaceRevision: number,
  ): Promise<BrowserConversationReply> {
    return this.initializedRequest(
      'conversation.discard',
      { sessionId, actionId, workspaceRevision },
      isBrowserConversationReply,
    );
  }

  async conversationReset(sessionId: string): Promise<void> {
    await this.initializedRequest(
      'conversation.reset',
      { sessionId },
      (result): result is null => result === null,
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
  | 'compile'
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
> & Partial<Pick<
  BrowserCompilerClient,
  | 'query'
  | 'conversationTurn'
  | 'conversationApply'
  | 'conversationDiscard'
  | 'conversationReset'
>>;

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

function throwIfConversationAborted(signal?: AbortSignal): void {
  if (signal?.aborted === true) {
    throw new DOMException('Conversation cancelled', 'AbortError');
  }
}

interface ConversationCitationWire {
  label: string;
  external_id: string;
  url: string;
  title: string;
  heading: string | null;
  score: number;
}

type ConversationReplyWire = BrowserConversationReplyValue & {
  retrieval_used?: boolean;
  citations?: ConversationCitationWire[];
  route_reason?: string;
};

function normalizeConversationTurnReply(
  result: BrowserConversationReply,
): ConversationTurnReply {
  const reply = result.reply as ConversationReplyWire;
  if (reply.retrieval_used !== true) {
    return result;
  }
  return {
    ...result,
    reply: {
      ...reply,
      retrievalUsed: true,
      routeReason: reply.route_reason ?? '',
      citations: (reply.citations ?? []).map((citation) => ({
        label: citation.label,
        externalId: citation.external_id,
        url: citation.url,
        title: citation.title,
        heading: citation.heading,
        score: citation.score,
      })),
    },
  };
}
