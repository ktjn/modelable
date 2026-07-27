import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from 'react';

import {
  initialAppState,
  workspaceAppReducer,
  type WorkspaceAppState,
} from './app-state';
import {
  BrowserCompilerClient,
  BrowserCompilerError,
  type BrowserCompilerClientLike,
  type CompileTarget,
} from './client';
import { normalizeDiagnosticsByUri } from './diagnostics';
import customerSource from './example-customer.mdl?raw';
import salesSource from './example-sales.mdl?raw';
import billingSource from './example-billing.mdl?raw';
import { SourceEditor } from './editor/SourceEditor';
import type { SourceEditorHandle } from './editor/types';
import {
  downloadText,
  downloadRecoveryData,
  type ImportedWorkspaceFile,
  sanitizeDownloadName,
} from './files';
import { usePersistentWorkspace } from './usePersistentWorkspace';
import { WorkspaceRecovery } from './WorkspaceRecovery';
import { WorkspaceFiles } from './WorkspaceFiles';
import { BrowserLanguageServiceController } from './language/BrowserLanguageServiceController';
import {
  createDefaultWorkspace,
  mutateWorkspace,
  mutateWorkspaceBatch,
  workspaceSources,
  type PlaygroundWorkspace,
  type WorkspaceMutation,
} from './workspace';
import {
  IndexedDbWorkspaceRepository,
  type WorkspaceRepository,
} from './workspace-repository';
import { CompatibilityView, GovernanceView } from './analysis/AnalysisViews';
import { useAnalysisData } from './analysis/useAnalysisData';
import { GraphPanelContainer } from './visualization/GraphPanelContainer';
import { ResizableLayout } from './layout/ResizableLayout';
import { BottomPanel } from './layout/BottomPanel';
import { WorkbenchHeader } from './layout/WorkbenchHeader';
import { Toolbar } from './layout/Toolbar';
import { MetricsFooter } from './layout/MetricsFooter';
import { ViewTabs, type MobileView } from './layout/ViewTabs';
import { RightPanel, type RightPanelTab } from './layout/RightPanel';
import { ChatPanel } from './ai/ChatPanel';
import {
  initialProviderState,
  providerStateReducer,
} from './ai/provider-state';
import { detectWebGpu, WebGpuProvider } from './ai/webgpu-provider';
import { HeuristicProvider } from './ai/heuristic-provider';
import type { AiGenerateAction, AiGenerateParameters } from './ai/types';
import {
  generateChatMessageId,
  isAssistantGenerateMessage,
  type AssistantChatMessage,
  type ChatMessage,
} from './ai/chat-types';
import { OutputPanel } from './output/OutputPanel';

const createBrowserCompilerClient = (): BrowserCompilerClientLike =>
  new BrowserCompilerClient();
const createWorkspaceRepository = (): WorkspaceRepository => {
  if (globalThis.indexedDB === undefined) {
    const unavailable = async (): Promise<never> => {
      throw new Error('IndexedDB is unavailable');
    };
    return {
      load: unavailable,
      save: unavailable,
      remove: unavailable,
    };
  }
  return new IndexedDbWorkspaceRepository(globalThis.indexedDB);
};
const performanceNow = (): number => performance.now();

const extensionMap: Record<CompileTarget, string> = {
  jsonSchema: '.json',
  typescript: '.ts',
  'sql-postgres': '.sql',
  'sql-clickhouse': '.sql',
  protobuf: '.proto',
  rust: '.rs',
  java: '.java',
  go: '.go',
  csharp: '.cs',
  markdown: '.md',
  python: '.py',
};

export interface AppProps {
  createClient?: () => BrowserCompilerClientLike;
  createRepository?: () => WorkspaceRepository;
  now?: () => number;
  confirmReplace?: (message: string) => boolean;
  download?: typeof downloadText;
}

function asCompilerError(error: unknown): BrowserCompilerError {
  if (error instanceof BrowserCompilerError) {
    return error;
  }
  return new BrowserCompilerError(
    'COMPILER_FAILED',
    'Compiler request failed',
  );
}

function hasErrorDiagnostics(
  diagnostics: { severity: string }[],
): boolean {
  return diagnostics.some((diagnostic) => diagnostic.severity === 'error');
}

function isTerminalLanguageError(error: BrowserCompilerError): boolean {
  return (
    error.code === 'COMPILER_FAILED' ||
    error.code === 'INITIALIZATION_FAILED' ||
    error.code === 'UNSUPPORTED_PROTOCOL'
  );
}

function exposeWorkspaceSourcesForTest(
  sources: ReturnType<typeof workspaceSources>,
): void {
  if (
    typeof window === 'undefined' ||
    new URLSearchParams(window.location.search).get('test') !== '1'
  ) {
    return;
  }
  (
    globalThis as typeof globalThis & {
      __modelableWorkspaceSourceUris?: string[];
    }
  ).__modelableWorkspaceSourceUris = sources.map((source) => source.uri);
}

export function App({
  createClient = createBrowserCompilerClient,
  createRepository = createWorkspaceRepository,
  now = performanceNow,
  confirmReplace = globalThis.confirm,
  download = downloadText,
}: AppProps) {
  const initialWorkspaceRef = useRef(
    createDefaultWorkspace([
      { path: 'customer.mdl', content: customerSource },
      { path: 'sales.mdl', content: salesSource },
      { path: 'billing.mdl', content: billingSource },
    ]),
  );
  const [repository] = useState(() => createRepository());
  const persistentWorkspace = usePersistentWorkspace({
    repository,
    defaultWorkspace: initialWorkspaceRef.current,
  });
  const [state, dispatch] = useReducer(
    workspaceAppReducer,
    initialWorkspaceRef.current,
    (workspace): WorkspaceAppState => {
      const { revision: _revision, ...appState } = initialAppState;
      return { ...appState, workspace };
    },
  );
  const [clientAttempt, setClientAttempt] = useState(0);
  const [statusIsError, setStatusIsError] = useState(false);
  const [languageController, setLanguageController] =
    useState<BrowserLanguageServiceController | null>(null);
  const [languageStatus, setLanguageStatus] = useState(
    'Language services starting…',
  );
  const [languageCanRetry, setLanguageCanRetry] = useState(false);
  const [mobileView, setMobileView] = useState<MobileView>('source');
  const [rightTab, setRightTab] = useState<RightPanelTab>('assistant');
  const [aiState, aiDispatch] = useReducer(
    providerStateReducer,
    initialProviderState,
  );
  const [aiPending, setAiPending] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const sourceEditorRef = useRef<SourceEditorHandle>(null);
  const clientRef = useRef<BrowserCompilerClientLike>(null);
  const languageControllerRef =
    useRef<BrowserLanguageServiceController>(null);
  const operationPendingRef = useRef(false);
  const recoveryPendingRef = useRef(false);
  const workspaceRef = useRef(state.workspace);
  workspaceRef.current = state.workspace;
  const workspaceRevisionRef = useRef(state.workspace.revision);
  workspaceRevisionRef.current = state.workspace.revision;

  useEffect(() => {
    if (workspaceRef.current !== persistentWorkspace.workspace) {
      workspaceRef.current = persistentWorkspace.workspace;
      dispatch({
        type: 'workspaceReplaced',
        workspace: persistentWorkspace.workspace,
      });
    }
  }, [persistentWorkspace.workspace]);

  useEffect(() => {
    const client = createClient();
    const controller = new BrowserLanguageServiceController(client, {
      onDiagnostics(revision, diagnostics) {
        if (
          languageControllerRef.current !== controller ||
          workspaceRef.current.revision !== revision
        ) {
          return;
        }
        setLanguageStatus('Language services synchronized');
        setLanguageCanRetry(false);
        dispatch({
          type: 'liveDiagnosticsPublished',
          revision,
          diagnostics,
        });
      },
      onError(error) {
        if (languageControllerRef.current !== controller) {
          return;
        }
        setLanguageStatus(error.message);
        setStatusIsError(true);
        if (isTerminalLanguageError(error)) {
          dispatch({
            type: 'runtimeFailed',
            message: error.message,
            duration: null,
          });
          setLanguageCanRetry(false);
        } else {
          setLanguageCanRetry(true);
        }
      },
    });
    const startedAt = now();
    clientRef.current = client;
    languageControllerRef.current = controller;
    setLanguageController(controller);
    setLanguageStatus('Language services starting…');
    setLanguageCanRetry(false);
    operationPendingRef.current = false;

    const exposedGlobal = globalThis as typeof globalThis & {
      __modelableBrowserCompiler?: BrowserCompilerClientLike;
    };
    if (
      typeof window !== 'undefined' &&
      new URLSearchParams(window.location.search).get('test') === '1'
    ) {
      exposedGlobal.__modelableBrowserCompiler = client;
    }

    const dispose = (): void => {
      if (languageControllerRef.current !== controller) {
        return;
      }
      languageControllerRef.current = null;
      clientRef.current = null;
      controller.dispose();
      setLanguageController(null);
      if (exposedGlobal.__modelableBrowserCompiler === client) {
        delete exposedGlobal.__modelableBrowserCompiler;
      }
    };
    const handlePageHide = (event: PageTransitionEvent): void => {
      recoveryPendingRef.current = event.persisted;
      dispose();
    };
    const handlePageShow = (event: PageTransitionEvent): void => {
      if (!event.persisted || !recoveryPendingRef.current) {
        return;
      }
      recoveryPendingRef.current = false;
      dispatch({ type: 'retryRequested' });
      setClientAttempt((attempt) => attempt + 1);
    };
    window.addEventListener('pagehide', handlePageHide);
    window.addEventListener('pageshow', handlePageShow);

    void client.initialize().then(
      () => {
        if (clientRef.current === client) {
          setStatusIsError(false);
          dispatch({ type: 'initialized', duration: now() - startedAt });
          controller.observe(workspaceRef.current);
          void controller.synchronize();
        }
      },
      (error: unknown) => {
        if (clientRef.current === client) {
          setStatusIsError(true);
          dispatch({
            type: 'runtimeFailed',
            message: asCompilerError(error).message,
            duration: now() - startedAt,
          });
        }
      },
    );

    return () => {
      window.removeEventListener('pagehide', handlePageHide);
      window.removeEventListener('pageshow', handlePageShow);
      dispose();
    };
  }, [clientAttempt, createClient, now]);

  useEffect(() => {
    if (
      state.runtime !== 'ready' ||
      persistentWorkspace.phase === 'restoring' ||
      persistentWorkspace.phase === 'recovery-required'
    ) {
      return;
    }
    const controller = languageControllerRef.current;
    if (controller === null) {
      return;
    }
    const sources = workspaceSources(persistentWorkspace.workspace);
    exposeWorkspaceSourcesForTest(sources);
    setLanguageStatus('Synchronizing language services…');
    controller.observe(persistentWorkspace.workspace);
  }, [
    persistentWorkspace.phase,
    persistentWorkspace.workspace,
    state.runtime,
  ]);

  const runOperation = useCallback(
    async (operation: 'validate' | 'format' | 'generate'): Promise<void> => {
      if (state.runtime !== 'ready' || operationPendingRef.current) {
        return;
      }
      const client = clientRef.current;
      const sourceEditor = sourceEditorRef.current;
      if (client === null || sourceEditor === null) {
        return;
      }

      const currentSource = sourceEditor.getSource();
      if (currentSource !== undefined) {
        const currentWorkspace = workspaceRef.current;
        const activeFile = currentWorkspace.files.find(
          (file) => file.path === currentWorkspace.activeFile,
        );
        if (activeFile !== undefined && activeFile.content !== currentSource.text) {
          const syncedWorkspace = mutateWorkspace(currentWorkspace, {
            type: 'update',
            path: activeFile.path,
            content: currentSource.text,
          });
          workspaceRef.current = syncedWorkspace;
          persistentWorkspace.replace(syncedWorkspace);
          dispatch({
            type: 'workspaceMutated',
            mutation: {
              type: 'update',
              path: activeFile.path,
              content: currentSource.text,
            },
          });
        }
      }

      const workspace = workspaceRef.current;
      const sources = workspaceSources(workspace);
      exposeWorkspaceSourcesForTest(sources);
      const revision = workspace.revision;
      const activePath = workspace.activeFile;
      const activeFile = workspace.files.find(
        (file) => file.path === activePath,
      );
      const activeSource = sources.find(
        (source) =>
          source.uri ===
          `file:///${activePath
            .split('/')
            .map(encodeURIComponent)
            .join('/')}`,
      );
      if (activeFile === undefined || activeSource === undefined) {
        return;
      }
      const startedAt = now();
      operationPendingRef.current = true;
      setStatusIsError(false);
      dispatch({ type: 'operationStarted', operation, revision });

      try {
        if (operation === 'validate') {
          const result = await client.openWorkspace(revision, sources);
          dispatch({
            type: 'operationSucceeded',
            operation,
            revision,
            diagnostics: result.diagnostics,
            duration: now() - startedAt,
          });
          setStatusIsError(false);
          return;
        }
        if (operation === 'format') {
          const result = await client.formatSource(activeSource);
          const currentWorkspace = workspaceRef.current;
          const currentFile = currentWorkspace.files.find(
            (file) => file.path === activePath,
          );
          if (
            result.replacement_text !== null &&
            !hasErrorDiagnostics(result.diagnostics) &&
            currentWorkspace.revision === revision &&
            currentWorkspace.activeFile === activePath &&
            currentFile?.version === activeFile.version
          ) {
            sourceEditor.applyFormattedText(
              activePath,
              result.replacement_text,
            );
          }
          dispatch({
            type: 'operationSucceeded',
            operation,
            revision,
            diagnostics: result.diagnostics,
            duration: now() - startedAt,
          });
          setStatusIsError(false);
          return;
        }

        const result = await client.compile(sources, state.compileTarget);
        const duration = now() - startedAt;
        if (
          hasErrorDiagnostics(result.diagnostics) ||
          result.artifacts.length === 0
        ) {
          setStatusIsError(true);
          dispatch({
            type: 'operationFailed',
            operation,
            revision,
            message: 'Generation failed',
            diagnostics: result.diagnostics,
            duration,
          });
          return;
        }
        setStatusIsError(false);
        dispatch({
          type: 'operationSucceeded',
          operation,
          revision,
          diagnostics: result.diagnostics,
          artifacts: result.artifacts,
          duration,
        });
        setRightTab('output');
      } catch (error: unknown) {
        const compilerError = asCompilerError(error);
        const duration = now() - startedAt;
        setStatusIsError(true);
        if (compilerError.code === 'COMPILER_FAILED') {
          dispatch({
            type: 'runtimeFailed',
            operation,
            revision,
            message: compilerError.message,
            duration,
          });
        } else {
          dispatch({
            type: 'operationFailed',
            operation,
            revision,
            message: compilerError.message,
            duration,
          });
        }
      } finally {
        operationPendingRef.current = false;
      }
    },
    [now, state.runtime, state.compileTarget],
  );

  const handleValidate = useCallback((): void => {
    void runOperation('validate');
  }, [runOperation]);
  const handleFormat = useCallback((): void => {
    void runOperation('format');
  }, [runOperation]);
  const handleGenerate = useCallback((): void => {
    void runOperation('generate');
  }, [runOperation]);

  const replaceWorkspace = useCallback(
    (workspace: PlaygroundWorkspace, immediate = false): void => {
      workspaceRef.current = workspace;
      persistentWorkspace.replace(workspace, { immediate });
      setStatusIsError(false);
      dispatch({ type: 'workspaceReplaced', workspace });
    },
    [persistentWorkspace.replace],
  );

  const applyWorkspaceMutation = useCallback(
    (mutation: WorkspaceMutation, immediate = false): void => {
      replaceWorkspace(
        mutateWorkspace(workspaceRef.current, mutation),
        immediate,
      );
    },
    [replaceWorkspace],
  );

  const importWorkspaceFiles = useCallback(
    (files: ImportedWorkspaceFile[]): void => {
      const current = workspaceRef.current;
      const existingPaths = new Set(
        current.files.map((file) => file.path),
      );
      const mutations: WorkspaceMutation[] = [];
      for (const file of files) {
        if (existingPaths.has(file.path)) {
          if (
            confirmReplace(
              `Replace existing workspace file ${file.path}?`,
            )
          ) {
            mutations.push({
              type: 'update',
              path: file.path,
              content: file.content,
            });
          }
        } else {
          mutations.push({
            type: 'create',
            path: file.path,
            content: file.content,
          });
        }
      }
      if (mutations.length > 0) {
        replaceWorkspace(
          mutateWorkspaceBatch(current, mutations),
          true,
        );
      }
    },
    [confirmReplace, replaceWorkspace],
  );

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (
        state.runtime !== 'ready' ||
        operationPendingRef.current
      ) {
        return;
      }
      const commandModifier = event.ctrlKey || event.metaKey;
      if (
        commandModifier &&
        event.shiftKey &&
        event.key === 'Enter'
      ) {
        event.preventDefault();
        handleValidate();
        return;
      }
      if (
        event.shiftKey &&
        event.altKey &&
        event.code === 'KeyF'
      ) {
        event.preventDefault();
        handleFormat();
        return;
      }
      if (
        commandModifier &&
        !event.shiftKey &&
        event.key === 'Enter'
      ) {
        event.preventDefault();
        handleGenerate();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleFormat, handleGenerate, handleValidate, state.runtime]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('ai') === 'heuristic') {
      const provider = new HeuristicProvider();
      aiDispatch({ type: 'download_start', provider });
      void provider.initialize().then(() => aiDispatch({ type: 'ready' }));
      return;
    }
    aiDispatch({ type: 'detect_start' });
    if (detectWebGpu()) {
      aiDispatch({ type: 'detect_available' });
    } else {
      aiDispatch({ type: 'detect_unsupported' });
    }
  }, []);

  const handleAiDownload = useCallback((): void => {
    if (aiState.status !== 'idle') {
      return;
    }
    const provider = new WebGpuProvider();
    aiDispatch({ type: 'download_start', provider });
    void provider
      .initialize((progress, message) => {
        aiDispatch({ type: 'download_progress', progress, message });
      })
      .then(
        () => aiDispatch({ type: 'ready' }),
        (error: unknown) =>
          aiDispatch({
            type: 'error',
            message: error instanceof Error ? error.message : 'Download failed',
          }),
      );
  }, [aiState.status]);

  const handleAiFallback = useCallback((): void => {
    const provider = new HeuristicProvider();
    aiDispatch({ type: 'download_start', provider });
    void provider.initialize().then(() => aiDispatch({ type: 'ready' }));
  }, []);

  const appendMessage = useCallback((message: ChatMessage): void => {
    setChatMessages((messages) => [...messages, message]);
  }, []);

  const updateAssistantMessage = useCallback(
    (id: string, update: Partial<AssistantChatMessage>): void => {
      setChatMessages((messages) =>
        messages.map((message) =>
          message.role === 'assistant' && message.id === id
            ? ({ ...message, ...update } as ChatMessage)
            : message,
        ),
      );
    },
    [],
  );

  const runAiGenerate = useCallback(
    (
      action: AiGenerateAction,
      parameters: AiGenerateParameters,
      userText: string,
    ): void => {
      const client = clientRef.current;
      const provider = aiState.provider;
      if (
        client === null ||
        provider === null ||
        aiState.status !== 'ready' ||
        state.runtime !== 'ready' ||
        aiPending
      ) {
        return;
      }
      const assistantId = generateChatMessageId();
      appendMessage({
        id: generateChatMessageId(),
        role: 'user',
        text: userText,
      });
      appendMessage({
        id: assistantId,
        role: 'assistant',
        kind: action === 'suggest_projection' ? 'generate' : 'generate',
        diagnostics: [],
        providerInfo: { provider: provider.id, model: provider.model },
        pending: true,
      });
      setAiPending(true);
      setRightTab('assistant');
      void client
        .aiGenerate(
          workspaceRef.current.revision,
          action,
          parameters,
          provider,
        )
        .then(
          (result) => {
            updateAssistantMessage(assistantId, {
              source: result.source,
              diagnostics: result.diagnostics,
              pending: false,
            });
          },
          (error: unknown) => {
            updateAssistantMessage(assistantId, {
              diagnostics: [
                {
                  code: 'AI_ERROR',
                  severity: 'error',
                  message:
                    error instanceof Error
                      ? error.message
                      : 'AI generation failed',
                  uri: '',
                  line: null,
                  column: null,
                  end_line: null,
                  end_column: null,
                },
              ],
              pending: false,
            });
          },
        )
        .finally(() => setAiPending(false));
    },
    [aiState.provider, aiState.status, aiPending, appendMessage, state.runtime, updateAssistantMessage],
  );

  const runAiExplain = useCallback(
    (userText: string): void => {
      const client = clientRef.current;
      const provider = aiState.provider;
      if (
        client === null ||
        provider === null ||
        aiState.status !== 'ready' ||
        state.runtime !== 'ready' ||
        aiPending
      ) {
        return;
      }
      const assistantId = generateChatMessageId();
      appendMessage({
        id: generateChatMessageId(),
        role: 'user',
        text: userText,
      });
      appendMessage({
        id: assistantId,
        role: 'assistant',
        kind: 'explain',
        diagnostics: [],
        providerInfo: { provider: provider.id, model: provider.model },
        pending: true,
      });
      setAiPending(true);
      setRightTab('assistant');
      void client.aiExplain(workspaceRef.current.revision, {}, provider).then(
        (result) => {
          updateAssistantMessage(assistantId, {
            explanation: result.explanation,
            pending: false,
          });
        },
        (error: unknown) => {
          updateAssistantMessage(assistantId, {
            diagnostics: [
              {
                code: 'AI_ERROR',
                severity: 'error',
                message:
                  error instanceof Error
                    ? error.message
                    : 'AI explanation failed',
                uri: '',
                line: null,
                column: null,
                end_line: null,
                end_column: null,
              },
            ],
            pending: false,
          });
        },
      ).finally(() => setAiPending(false));
    },
    [aiState.provider, aiState.status, aiPending, appendMessage, state.runtime, updateAssistantMessage],
  );

  const handleChatSend = useCallback(
    (text: string): void => {
      runAiGenerate('generate_entity', { description: text }, text);
    },
    [runAiGenerate],
  );

  const handleAiExplain = useCallback((): void => {
    runAiExplain('Explain the workspace');
  }, [runAiExplain]);

  const handleAiSuggestProjection = useCallback((): void => {
    runAiGenerate('suggest_projection', {}, 'Suggest a projection');
  }, [runAiGenerate]);

  const markLatestGenerateOutcome = useCallback(
    (outcome: 'accepted' | 'discarded'): void => {
      setChatMessages((messages) => {
        for (let index = messages.length - 1; index >= 0; index -= 1) {
          const message = messages[index];
          if (
            message !== undefined &&
            isAssistantGenerateMessage(message) &&
            message.outcome === undefined
          ) {
            const next = [...messages];
            next[index] = { ...message, outcome };
            return next;
          }
        }
        return messages;
      });
    },
    [],
  );

  const handleAiAccept = useCallback(
    (source: string): void => {
      if (source === '') {
        return;
      }
      const workspace = workspaceRef.current;
      const activePath = workspace.activeFile;
      const updated = mutateWorkspace(workspace, {
        type: 'update',
        path: activePath,
        content: source,
      });
      const withProvenance: PlaygroundWorkspace = {
        ...updated,
        metadata: {
          ...updated.metadata,
          lastAiAccept: {
            provider: aiState.provider?.id ?? 'unknown',
            model: aiState.provider?.model ?? 'unknown',
            timestamp: Date.now(),
          },
        },
      };
      replaceWorkspace(withProvenance, true);
      sourceEditorRef.current?.replaceText(source);
      markLatestGenerateOutcome('accepted');
    },
    [aiState.provider?.id, aiState.provider?.model, markLatestGenerateOutcome, replaceWorkspace],
  );

  const handleAiDiscard = useCallback(
    (messageId: string): void => {
      setChatMessages((messages) =>
        messages.map((message) =>
          message.role === 'assistant' && message.id === messageId
            ? ({ ...message, outcome: 'discarded' } as ChatMessage)
            : message,
        ),
      );
    },
    [],
  );

  const retryCompiler = (): void => {
    const controller = languageControllerRef.current;
    languageControllerRef.current = null;
    clientRef.current = null;
    controller?.dispose();
    operationPendingRef.current = false;
    setStatusIsError(false);
    dispatch({ type: 'retryRequested' });
    setClientAttempt((attempt) => attempt + 1);
  };

  const exportSource = (): void => {
    const source = state.workspace.files.find(
      (file) => file.path === state.workspace.activeFile,
    );
    if (source === undefined) {
      return;
    }
    download(
      source.content,
      sanitizeDownloadName(source.path, '.mdl'),
      'text/plain',
    );
  };

  const handleRetryLanguageServices = useCallback((): void => {
    setLanguageStatus('Retrying language services…');
    setLanguageCanRetry(false);
    void languageControllerRef.current?.retry();
  }, []);

  const handleRetryStorage = useCallback((): void => {
    void persistentWorkspace.retry();
  }, [persistentWorkspace.retry]);

  const handleCompileTargetChange = useCallback(
    (target: CompileTarget): void => {
      dispatch({ type: 'compileTargetSelected', target });
    },
    [],
  );

  const sourceUris = workspaceSources(state.workspace).map(
    (source) => source.uri,
  );
  const markersByUri = normalizeDiagnosticsByUri(
    state.diagnostics,
    sourceUris,
  );
  const selectedArtifact =
    state.artifacts.find(
      (artifact) => artifact.path === state.selectedArtifactPath,
    ) ?? null;

  const handleExportArtifact = useCallback(
    (path: string): void => {
      const artifact = state.artifacts.find((item) => item.path === path);
      if (artifact === undefined) {
        return;
      }
      download(
        artifact.content,
        sanitizeDownloadName(artifact.path, extensionMap[state.compileTarget]),
        artifact.media_type,
      );
    },
    [download, state.artifacts, state.compileTarget],
  );

  const handleExportAllArtifacts = useCallback((): void => {
    for (const artifact of state.artifacts) {
      download(
        artifact.content,
        sanitizeDownloadName(artifact.path, extensionMap[state.compileTarget]),
        artifact.media_type,
      );
    }
  }, [download, state.artifacts, state.compileTarget]);

  const artifactIsStale =
    state.artifacts.length > 0 &&
    state.artifactRevision !== state.workspace.revision;
  const actionsDisabled =
    state.runtime !== 'ready' ||
    persistentWorkspace.phase === 'restoring' ||
    persistentWorkspace.phase === 'recovery-required';
  const diagnosticLabel = `${state.diagnostics.length} ${
    state.diagnostics.length === 1 ? 'diagnostic' : 'diagnostics'
  }`;
  const getWorkspace = useCallback(
    (): PlaygroundWorkspace => workspaceRef.current,
    [],
  );
  const analysisData = useAnalysisData({
    clientRef,
    runtimeReady: state.runtime === 'ready',
    workspaceRevisionRef,
  });

  if (persistentWorkspace.phase === 'restoring') {
    return (
      <main className="workbench">
        <section className="workspace-loading" aria-live="polite">
          <p className="eyebrow">Local schema workbench</p>
          <h1>Modelable playground</h1>
          <p>Restoring local workspace…</p>
        </section>
      </main>
    );
  }

  if (
    persistentWorkspace.phase === 'recovery-required' &&
    persistentWorkspace.recovery !== null
  ) {
    return (
      <main className="workbench">
        <WorkspaceRecovery
          reason={persistentWorkspace.recovery.reason}
          onExport={() =>
            downloadRecoveryData(
              persistentWorkspace.recovery?.raw,
              download,
            )
          }
          onReset={() => void persistentWorkspace.reset()}
          onRetry={() => void persistentWorkspace.retry()}
        />
      </main>
    );
  }

  const activeFileContent =
    state.workspace.files.find((file) => file.path === state.workspace.activeFile)
      ?.content ?? '';

  return (
    <main className="workbench" data-state={state.runtime} data-mobile-view={mobileView}>
      <WorkbenchHeader
        status={state.status}
        diagnosticLabel={diagnosticLabel}
        statusIsError={statusIsError}
        persistencePhase={persistentWorkspace.phase}
        languageStatus={languageStatus}
      />
      <Toolbar
        runtime={state.runtime}
        compileTarget={state.compileTarget}
        actionsDisabled={actionsDisabled}
        languageCanRetry={languageCanRetry}
        persistencePhase={persistentWorkspace.phase}
        onExportSource={exportSource}
        onValidate={handleValidate}
        onFormat={handleFormat}
        onGenerate={handleGenerate}
        onRetryCompiler={retryCompiler}
        onRetryLanguageServices={handleRetryLanguageServices}
        onRetryStorage={handleRetryStorage}
        onCompileTargetChange={handleCompileTargetChange}
      />
      <ViewTabs mobileView={mobileView} onChange={setMobileView} />
      <ResizableLayout
        mobileView={mobileView}
        explorer={
          <WorkspaceFiles
            workspace={state.workspace}
            disabled={actionsDisabled}
            onCreate={(path) =>
              applyWorkspaceMutation({ type: 'create', path }, true)
            }
            onImport={importWorkspaceFiles}
            onRename={(path) =>
              applyWorkspaceMutation({
                type: 'rename',
                from: workspaceRef.current.activeFile,
                to: path,
              }, true)
            }
            onDelete={() => {
              const activeFile = workspaceRef.current.activeFile;
              if (
                confirmReplace(
                  `Delete workspace file ${activeFile}?`,
                )
              ) {
                applyWorkspaceMutation({
                  type: 'delete',
                  path: activeFile,
                }, true);
              }
            }}
            onSelect={(path) =>
              applyWorkspaceMutation({ type: 'select', path })
            }
          />
        }
        editor={
          <section
            className="editor-pane"
            id="source-editor"
            aria-label="Modelable source"
            tabIndex={-1}
            onFocus={(event) => {
              if (event.target === event.currentTarget) {
                sourceEditorRef.current?.focus();
              }
            }}
          >
            <SourceEditor
              ref={sourceEditorRef}
              files={state.workspace.files}
              activeFile={state.workspace.activeFile}
              markersByUri={markersByUri}
              languageController={languageController ?? undefined}
              getWorkspace={getWorkspace}
              onContentChange={(path, content) => {
                workspaceRef.current = mutateWorkspace(
                  workspaceRef.current,
                  { type: 'update', path, content },
                );
                persistentWorkspace.replace(workspaceRef.current);
                setStatusIsError(false);
                dispatch({
                  type: 'workspaceMutated',
                  mutation: { type: 'update', path, content },
                });
              }}
            />
          </section>
        }
        visualization={
          <RightPanel
            activeTab={rightTab}
            onTabChange={setRightTab}
            assistant={
              <ChatPanel
                messages={chatMessages}
                activeFileContent={activeFileContent}
                aiState={aiState}
                actionsDisabled={actionsDisabled}
                onSend={handleChatSend}
                onExplain={handleAiExplain}
                onSuggestProjection={handleAiSuggestProjection}
                onAccept={handleAiAccept}
                onDiscard={handleAiDiscard}
                onDownloadModel={handleAiDownload}
                onUseHeuristic={handleAiFallback}
              />
            }
            graph={
              <section
                className="graph-pane"
                aria-label="Model graph visualization"
                data-testid="graph"
              >
                <GraphPanelContainer
                  clientRef={clientRef}
                  runtimeReady={state.runtime === 'ready'}
                  languageRevision={state.languageRevision}
                />
              </section>
            }
            output={
              <OutputPanel
                artifacts={state.artifacts}
                selectedArtifactPath={state.selectedArtifactPath}
                isStale={artifactIsStale}
                disabled={actionsDisabled}
                onSelect={(path) =>
                  dispatch({ type: 'artifactSelected', path })
                }
                onDownload={handleExportArtifact}
                onDownloadAll={handleExportAllArtifacts}
              />
            }
          />
        }
        bottom={
          <BottomPanel
            diagnostics={
              <section
                className="diagnostics"
                aria-label="Document diagnostics"
                data-testid="diagnostics"
              >
                <h2>Diagnostics</h2>
                {state.diagnostics.length > 0 ? (
                  <ul>
                    {state.diagnostics.map((diagnostic, index) => (
                      <li key={`${diagnostic.code}-${index}`}>
                        <strong>{diagnostic.code}</strong>{' '}
                        {diagnostic.message}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No diagnostics</p>
                )}
              </section>
            }
            compatibility={
              <div className="analysis-panel__body" data-testid="analysis">
                <CompatibilityView result={analysisData.compatibility} />
              </div>
            }
            governance={
              <div className="analysis-panel__body" data-testid="analysis">
                <GovernanceView result={analysisData.governance} />
              </div>
            }
          />
        }
      />
      <MetricsFooter
        initializationDuration={state.initializationDuration}
        lastOperationDuration={state.lastOperationDuration}
      />
    </main>
  );
}
