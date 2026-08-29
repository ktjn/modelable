import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  useMemo,
} from 'react';

import {
  initialAppState,
  workspaceAppReducer,
  type WorkspaceAppState,
} from './app-state';
import {
  BrowserCompilerClient,
  BrowserCompilerError,
  COMPILE_TARGET_LABELS,
  type BrowserCompilerClientLike,
  type CompileTarget,
} from './client';
import { normalizeDiagnosticsByUri } from './diagnostics';
import type { BrowserDiagnostic } from './protocol';
import customerSource from './example-customer.mdl?raw';
import salesSource from './example-sales.mdl?raw';
import billingSource from './example-billing.mdl?raw';
import workspaceSource from './example-workspace.mdl?raw';
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
  pathFromSourceUri,
  sourceUriFromPath,
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
import { CommandPalette, type CommandPaletteCommand } from './layout/CommandPalette';
import { ShortcutsHelp, type ShortcutEntry } from './layout/ShortcutsHelp';
import { ChatPanel } from './ai/ChatPanel';
import {
  initialProviderState,
  providerStateReducer,
  type ProviderKind,
} from './ai/provider-state';
import {
  OllamaProvider,
  listOllamaModels,
  OLLAMA_DEFAULT_BASE_URL,
} from './ai/ollama-provider';
import { ToastProvider, useToasts } from './Toast';
import { toErrorMessage } from './errors';
import {
  DEFAULT_MODELS,
  createModelOption,
  detectWebGpu,
  WebGpuProvider,
  getGpuLimits,
  suggestModels,
  type ModelOption,
  type SuggestedModelTiers,
} from './ai/webgpu-provider';
import { SimulatorProvider } from './ai/simulator-provider';
import {
  generateChatMessageId,
  type AssistantDocsChatMessage,
  isAssistantGenerateMessage,
  type AssistantChatMessage,
  type ChatMessage,
} from './ai/chat-types';
import { OutputPanel } from './output/OutputPanel';
import { useTheme, type ThemePreference } from './theme';
import {
  createPlaygroundPluginRegistry,
  type PlaygroundPlugin,
} from './plugins/registry';

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
  plugins?: readonly PlaygroundPlugin[];
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

/** Surfaces an assistant-side failure through the chat message's diagnostics. */
function aiDiagnostic(
  code: 'AI_ERROR' | 'AI_APPLY_ERROR',
  message: string,
): BrowserDiagnostic {
  return {
    code,
    severity: 'error',
    message,
    uri: '',
    line: null,
    column: null,
    end_line: null,
    end_column: null,
  };
}

/** Workspace path for a source URI returned by a conversation apply. */
function conversationSourcePath(uri: string): string {
  return decodeURIComponent(new URL(uri).pathname.slice(1));
}

type RecommendedTier = NonNullable<ModelOption['recommendedTier']>;

const tierOrder: Record<RecommendedTier, number> = {
  fast: 0,
  balanced: 1,
  quality: 2,
};

/** Recommended models sort ahead of the rest, then by ascending VRAM. */
function tierRank(tier: RecommendedTier | undefined): number {
  return tier === undefined ? 3 : tierOrder[tier];
}

function recommendedTierFor(
  modelId: string,
  suggested: SuggestedModelTiers,
): RecommendedTier | undefined {
  switch (modelId) {
    case suggested.fast:
      return 'fast';
    case suggested.balanced:
      return 'balanced';
    case suggested.quality:
      return 'quality';
    default:
      return undefined;
  }
}

/** Appends models that are not already listed, preserving the current order. */
function mergeModelOptions(
  current: ModelOption[],
  incoming: readonly ModelOption[],
): ModelOption[] {
  const merged = [...current];
  for (const model of incoming) {
    if (!merged.some((existing) => existing.id === model.id)) {
      merged.push(model);
    }
  }
  return merged;
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

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target.isContentEditable
  ) {
    return true;
  }
  // Monaco's native EditContext input surface is a plain
  // `<div role="textbox">` -- not a textarea and not contentEditable --
  // so it would otherwise slip past the checks above.
  return target.closest('[role="textbox"], .monaco-editor') !== null;
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

export function App(props: AppProps) {
  return (
    <ToastProvider>
      <AppInner {...props} />
    </ToastProvider>
  );
}

function AppInner({
  createClient = createBrowserCompilerClient,
  createRepository = createWorkspaceRepository,
  now = performanceNow,
  confirmReplace = globalThis.confirm,
  download = downloadText,
  plugins = [],
}: AppProps) {
  const pluginRegistry = useMemo(
    () => createPlaygroundPluginRegistry(plugins),
    [plugins],
  );
  const initialWorkspaceRef = useRef(
    createDefaultWorkspace([
      { path: 'customer.mdl', content: customerSource },
      { path: 'sales.mdl', content: salesSource },
      { path: 'billing.mdl', content: billingSource },
      { path: 'workspace.mdl', content: workspaceSource },
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
  const { preference: themePreference, resolvedTheme, setPreference: setThemePreference } = useTheme();
  const [mobileView, setMobileView] = useState<MobileView>('source');
  const [rightTab, setRightTab] = useState<RightPanelTab>('assistant');
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [shortcutsHelpOpen, setShortcutsHelpOpen] = useState(false);
  const [aiState, aiDispatch] = useReducer(
    providerStateReducer,
    initialProviderState,
  );
  const { push: pushToast } = useToasts();
  const [aiPending, setAiPending] = useState(false);
  const [models, setModels] = useState<ModelOption[]>(DEFAULT_MODELS);
  const [selectedModel, setSelectedModel] = useState(DEFAULT_MODELS[0]!.id);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const conversationSessionIdRef = useRef(crypto.randomUUID());
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
        (source) => source.uri === sourceUriFromPath(activePath),
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

  const revealDiagnostic = useCallback(
    (diagnostic: BrowserDiagnostic): void => {
      if (diagnostic.line === null || diagnostic.column === null) {
        return;
      }
      const path = pathFromSourceUri(diagnostic.uri);
      if (!workspaceRef.current.files.some((file) => file.path === path)) {
        return;
      }
      applyWorkspaceMutation({ type: 'select', path }, true);
      setMobileView('source');
      sourceEditorRef.current?.revealPosition(
        path,
        diagnostic.line,
        diagnostic.column,
      );
    },
    [applyWorkspaceMutation],
  );

  const importWorkspaceFiles = useCallback(
    (files: ImportedWorkspaceFile[]): void => {
      const current = workspaceRef.current;
      const existingPaths = new Set(
        current.files.map((file) => file.path),
      );
      const mutations: WorkspaceMutation[] = files.map((file) =>
        existingPaths.has(file.path)
          ? { type: 'update', path: file.path, content: file.content }
          : { type: 'create', path: file.path, content: file.content },
      );
      if (mutations.length > 0) {
        replaceWorkspace(
          mutateWorkspaceBatch(current, mutations),
          true,
        );
      }
    },
    [replaceWorkspace],
  );

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      const commandModifier = event.ctrlKey || event.metaKey;
      if (
        commandModifier &&
        !event.shiftKey &&
        !event.altKey &&
        event.key.toLowerCase() === 'k'
      ) {
        event.preventDefault();
        setCommandPaletteOpen((isOpen) => !isOpen);
        return;
      }
      if (
        !commandModifier &&
        !event.shiftKey &&
        !event.altKey &&
        event.key === '?' &&
        !isEditableTarget(event.target)
      ) {
        event.preventDefault();
        setShortcutsHelpOpen((isOpen) => !isOpen);
        return;
      }
      if (
        state.runtime !== 'ready' ||
        operationPendingRef.current
      ) {
        return;
      }
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
    if (params.get('ai') === 'simulator') {
      const provider = new SimulatorProvider();
      aiDispatch({ type: 'download_start', provider });
      void provider.initialize().then(() => aiDispatch({ type: 'ready' }));
      return;
    }
    aiDispatch({ type: 'detect_start' });
    const modelParam = params.get('model');
    if (modelParam !== null) {
      setModels((current) =>
        mergeModelOptions(current, [createModelOption(modelParam)]),
      );
      setSelectedModel(modelParam);
    }

    const modelsUrlParam = params.get('models_url');
    if (modelsUrlParam !== null) {
      handleAiFetchModels(modelsUrlParam);
    }

    if (detectWebGpu()) {
      aiDispatch({ type: 'detect_available' });
      void WebGpuProvider.getWebLlmModels()
        .then((webLlmModels) => {
          setModels((current) => mergeModelOptions(current, webLlmModels));

          void getGpuLimits()
            .then((limits) => {
              setModels((current) => {
                const suggested = suggestModels(current, limits);
                const updated = current
                  .map((m) => ({
                    ...m,
                    recommendedTier: recommendedTierFor(m.id, suggested),
                  }))
                  .sort((a, b) => {
                    const aRank = tierRank(a.recommendedTier);
                    const bRank = tierRank(b.recommendedTier);
                    if (aRank !== bRank) return aRank - bRank;
                    return a.vramMb - b.vramMb;
                  });

                if (params.get('model') === null && suggested.fast !== undefined) {
                  setSelectedModel(suggested.fast);
                }
                return updated;
              });
            })
            .catch((error: unknown) => {
              const message = toErrorMessage(error, 'Failed to detect GPU limits');
              pushToast('error', message);
            });
        })
        .catch((error: unknown) => {
          const message = toErrorMessage(error, 'Failed to list WebLLM models');
          pushToast('error', message);
          aiDispatch({ type: 'error', message });
        });
    } else {
      aiDispatch({ type: 'detect_unsupported' });
    }
  }, []);

  const handleAiDownload = useCallback((): void => {
    if (aiState.status !== 'idle' && aiState.status !== 'error') {
      return;
    }
    if (aiState.providerKind === 'ollama') {
      const provider = new OllamaProvider(selectedModel, OLLAMA_DEFAULT_BASE_URL);
      aiDispatch({ type: 'download_start', provider, message: 'Connecting to Ollama…' });
      void provider.initialize().then(
        () => aiDispatch({ type: 'ready' }),
        (error: unknown) => {
          const message = toErrorMessage(error, 'Could not connect to Ollama');
          pushToast('error', message);
          aiDispatch({ type: 'error', message });
        },
      );
      return;
    }
    const config = models.find((m) => m.id === selectedModel);
    if (config === undefined) {
      return;
    }
    const provider = new WebGpuProvider(config);
    aiDispatch({ type: 'download_start', provider });
    void provider
      .initialize((progress, message) => {
        aiDispatch({ type: 'download_progress', progress, message });
      })
      .then(
        () => aiDispatch({ type: 'ready' }),
        (error: unknown) => {
          const message = toErrorMessage(error, 'Download failed');
          pushToast('error', message);
          aiDispatch({ type: 'error', message });
        },
      );
  }, [aiState.status, aiState.providerKind, selectedModel, models]);

  const handleAiProviderKindChange = useCallback((kind: ProviderKind): void => {
    aiDispatch({ type: 'set_provider_kind', kind });
    if (kind !== 'ollama') {
      return;
    }
    aiDispatch({ type: 'detect_start' });
    listOllamaModels(OLLAMA_DEFAULT_BASE_URL)
      .then((names) => {
        if (names.length === 0) {
          aiDispatch({
            type: 'error',
            message: 'No models installed on Ollama. Run "ollama pull <model>" and try again.',
          });
          return;
        }
        setModels(
          names.map((name) => ({
            id: name,
            label: name,
            description: 'Installed locally',
            vramMb: 0,
          })),
        );
        setSelectedModel(names[0]!);
        aiDispatch({ type: 'detect_available' });
      })
      .catch((error: unknown) => {
        const message = toErrorMessage(error, 'Could not reach Ollama');
        aiDispatch({ type: 'error', message });
      });
  }, []);

  const handleAiReset = useCallback((): void => {
    if (aiState.provider) {
      void aiState.provider.dispose();
    }
    aiDispatch({ type: 'reset' });
  }, [aiState.provider]);

  const handleAiAddModel = useCallback((id: string): void => {
    setModels((current) => mergeModelOptions(current, [createModelOption(id)]));
    setSelectedModel(id);
  }, []);

  const handleAiFetchModels = useCallback((url: string): void => {
    aiDispatch({
      type: 'download_progress',
      progress: 0,
      message: `Fetching models from ${url}...`,
    });
    fetch(url)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to fetch models: ${res.statusText}`);
        }
        return res.json() as Promise<ModelOption[]>;
      })
      .then((newModels) => {
        setModels((current) => mergeModelOptions(current, newModels));
        if (newModels.length > 0) {
          setSelectedModel(newModels[0]!.id);
        }
        aiDispatch({ type: 'reset' });
      })
      .catch((error: unknown) => {
        const message = toErrorMessage(error, 'Fetch failed');
        pushToast('error', message);
        aiDispatch({ type: 'error', message });
      });
  }, []);

  const handleAiFallback = useCallback((): void => {
    const provider = new SimulatorProvider();
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

  const runConversation = useCallback(
    (userText: string): void => {
      const client = clientRef.current;
      const provider = aiState.provider;
      if (
        client === null ||
        client.conversationTurn === undefined ||
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
      const position = sourceEditorRef.current?.getPosition() ?? null;
      void client.conversationTurn(
        {
          sessionId: conversationSessionIdRef.current,
          workspaceRevision: workspaceRef.current.revision,
          message: userText,
          activeDocumentUri: position?.uri ?? null,
          position: position === null
            ? null
            : { line: position.line, character: position.character },
          documentationIndexUrl: new URL(
            'docs-index/manifest.json',
            new URL(import.meta.env.BASE_URL, window.location.href),
          ).href,
          documentationAssetRoot: new URL(
            'docs-index/',
            new URL(import.meta.env.BASE_URL, window.location.href),
          ).href,
          automaticDocumentation: true,
        },
        provider,
      )
        .then(
          (result) => {
            const preview = result.reply.preview_files[0];
            setChatMessages((messages) =>
              messages.map((message) => {
                if (message.role !== 'assistant' || message.id !== assistantId) {
                  return message;
                }
                if (
                  result.reply.kind === 'preview' &&
                  (preview !== undefined || result.reply.compilation_files.length > 0)
                ) {
                    return {
                      id: assistantId,
                      role: 'assistant',
                      kind: 'generate',
                      actionId: result.reply.change_set_id ?? undefined,
                      assumptions: result.reply.assumptions ?? [],
                      changed: result.reply.changed ?? [],
                      affected: result.reply.affected ?? [],
                      previewFiles: result.reply.preview_files,
                      compilationFiles: result.reply.compilation_files,
                      diagnostics: [],
                      providerInfo: { provider: provider.id, model: provider.model },
                      pending: false,
                    };
                }
                if (result.reply.retrievalUsed === true) {
                  const [answer = ''] = result.reply.text.split('\n\nSources:\n', 1);
                  return {
                    id: assistantId,
                    role: 'assistant',
                    kind: 'docs',
                    answer,
                    citations: result.reply.citations ?? [],
                    routeReason: result.reply.routeReason,
                    diagnostics: [],
                    providerInfo: { provider: provider.id, model: provider.model },
                    pending: false,
                  } satisfies AssistantDocsChatMessage;
                }
                return {
                  id: assistantId,
                  role: 'assistant',
                  kind: 'explain',
                  explanation: result.reply.text,
                  diagnostics: [],
                  providerInfo: { provider: provider.id, model: provider.model },
                  pending: false,
                };
              }),
            );
          },
          (error: unknown) => {
            updateAssistantMessage(assistantId, {
              diagnostics: [
                aiDiagnostic(
                  'AI_ERROR',
                  toErrorMessage(error, 'Conversation failed'),
                ),
              ],
              pending: false,
            });
          },
        )
        .finally(() => setAiPending(false));
    },
    [aiState.provider, aiState.status, aiPending, appendMessage, state.runtime, updateAssistantMessage],
  );

  const handleChatSend = useCallback(
    (text: string): void => {
      if (text.trim() === '/reset') {
        const reset = clientRef.current?.conversationReset;
        if (reset !== undefined) {
          setAiPending(true);
          void reset(conversationSessionIdRef.current)
            .then(() => {
              conversationSessionIdRef.current = crypto.randomUUID();
              setChatMessages([]);
            })
            .finally(() => setAiPending(false));
          return;
        }
      }
      runConversation(text);
    },
    [runConversation],
  );

  const handleAiExplain = useCallback((): void => {
    runConversation('Describe the focused definition or workspace');
  }, [runConversation]);

  const handleAiSuggestProjection = useCallback((): void => {
    runConversation('Suggest a projection for the focused model');
  }, [runConversation]);

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
    (source: string, actionId?: string): void => {
      const client = clientRef.current;
      if (actionId !== undefined && client?.conversationApply !== undefined) {
        const reportApplyFailure = (message: string): void => {
          setChatMessages((messages) =>
            messages.map((candidate) =>
              candidate.role === 'assistant' &&
              candidate.kind === 'generate' &&
              candidate.actionId === actionId
                ? {
                    ...candidate,
                    diagnostics: [aiDiagnostic('AI_APPLY_ERROR', message)],
                  }
                : candidate,
            ),
          );
        };
        void client.conversationApply(
          conversationSessionIdRef.current,
          actionId,
          workspaceRef.current.revision,
        ).then((result) => {
          if (result.reply.kind !== 'applied') {
            reportApplyFailure(result.reply.text);
            return;
          }
          if (result.reply.operation_kind === 'compile') {
            const artifacts = result.reply.compilation_files
              .filter((file) => file.after_text !== null)
              .map((file) => ({
                path: file.destination,
                media_type: file.media_type,
                content: file.after_text ?? '',
                source_refs: [],
                warnings: [],
              }));
            dispatch({
              type: 'operationSucceeded',
              operation: 'generate',
              revision: workspaceRef.current.revision,
              diagnostics: [],
              artifacts,
              duration: 0,
            });
            setRightTab('output');
            markLatestGenerateOutcome('accepted');
            return;
          }
          const current = workspaceRef.current;
          const currentByPath = new Map(
            current.files.map((file) => [file.path, file]),
          );
          const returnedByPath = new Map(
            result.sources.map((item) => [conversationSourcePath(item.uri), item]),
          );
          for (const item of result.sources) {
            const path = conversationSourcePath(item.uri);
            const existing = currentByPath.get(path);
            if (existing?.content !== item.text) {
              sourceEditorRef.current?.applyFormattedText(path, item.text);
            }
          }
          const updated = {
            ...current,
            revision: result.workspace_revision,
            files: [...returnedByPath.entries()].map(([path, item]) => ({
              path,
              content: item.text,
              version: item.version,
            })),
          };
          replaceWorkspace(updated, true);
          markLatestGenerateOutcome('accepted');
        }).catch((error: unknown) => {
          reportApplyFailure(
            toErrorMessage(error, 'Could not apply conversation preview'),
          );
        });
        return;
      }
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
      const message = chatMessages.find((item) => item.id === messageId);
      const actionId =
        message !== undefined && isAssistantGenerateMessage(message)
          ? message.actionId
          : undefined;
      const client = clientRef.current;
      if (actionId !== undefined && client?.conversationDiscard !== undefined) {
        void client.conversationDiscard(
          conversationSessionIdRef.current,
          actionId,
          workspaceRef.current.revision,
        );
      }
      setChatMessages((messages) =>
        messages.map((message) =>
          message.role === 'assistant' && message.id === messageId
            ? ({ ...message, outcome: 'discarded' } as ChatMessage)
            : message,
        ),
      );
    },
    [chatMessages],
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

  const handleResetToDemo = useCallback((): void => {
    if (
      !confirmReplace(
        'Discard local changes and reload the built-in demo workspace?',
      )
    ) {
      return;
    }
    void persistentWorkspace.reset();
  }, [confirmReplace, persistentWorkspace.reset]);

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
  const compatibilityIssueCount =
    analysisData.compatibility?.reports.filter(
      (report) => report.status === 'breaking',
    ).length ?? 0;
  const governanceFindingCount = analysisData.governance?.findings.length ?? 0;

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

  const commands: CommandPaletteCommand[] = [];
  if (!actionsDisabled) {
    commands.push(
      {
        id: 'action-validate',
        group: 'Actions',
        label: 'Validate',
        hint: 'Ctrl+Shift+Enter',
        onRun: handleValidate,
      },
      {
        id: 'action-format',
        group: 'Actions',
        label: 'Format',
        hint: 'Shift+Alt+F',
        onRun: handleFormat,
      },
      {
        id: 'action-generate',
        group: 'Actions',
        label: 'Generate',
        hint: 'Ctrl+Enter',
        onRun: handleGenerate,
      },
    );
  }
  commands.push(
    {
      id: 'action-export-source',
      group: 'Actions',
      label: 'Export source',
      onRun: exportSource,
    },
    {
      id: 'action-reload-demo',
      group: 'Actions',
      label: 'Reload demo data',
      onRun: handleResetToDemo,
    },
  );
  if (state.runtime === 'failed') {
    commands.push({
      id: 'action-retry-compiler',
      group: 'Actions',
      label: 'Retry compiler',
      onRun: retryCompiler,
    });
  }
  if (state.runtime !== 'failed' && languageCanRetry) {
    commands.push({
      id: 'action-retry-language-services',
      group: 'Actions',
      label: 'Retry language services',
      onRun: handleRetryLanguageServices,
    });
  }
  if (persistentWorkspace.phase === 'memory-only') {
    commands.push({
      id: 'action-retry-storage',
      group: 'Actions',
      label: 'Retry storage',
      onRun: handleRetryStorage,
    });
  }
  if (!actionsDisabled) {
    for (const target of Object.keys(COMPILE_TARGET_LABELS) as CompileTarget[]) {
      commands.push({
        id: `target-${target}`,
        group: 'Target language',
        label: `Set target: ${COMPILE_TARGET_LABELS[target]}`,
        hint: target === state.compileTarget ? 'Current' : undefined,
        onRun: () => handleCompileTargetChange(target),
      });
    }
  }
  commands.push(
    {
      id: 'panel-files',
      group: 'Panels',
      label: 'View: Files',
      onRun: () => setMobileView('files'),
    },
    {
      id: 'panel-source',
      group: 'Panels',
      label: 'View: Source',
      onRun: () => setMobileView('source'),
    },
    {
      id: 'panel-assistant',
      group: 'Panels',
      label: 'Inspect: Assistant',
      onRun: () => {
        setRightTab('assistant');
        setMobileView('assistant');
      },
    },
    {
      id: 'panel-graph',
      group: 'Panels',
      label: 'Inspect: Graph',
      onRun: () => {
        setRightTab('graph');
        setMobileView('assistant');
      },
    },
    {
      id: 'panel-output',
      group: 'Panels',
      label: 'Inspect: Output',
      onRun: () => {
        setRightTab('output');
        setMobileView('assistant');
      },
    },
    {
      id: 'panel-diagnostics',
      group: 'Panels',
      label: 'View: Diagnostics',
      onRun: () => setMobileView('analysis'),
    },
  );
  if (!actionsDisabled) {
    for (const file of state.workspace.files) {
      if (file.path === state.workspace.activeFile) {
        continue;
      }
      commands.push({
        id: `open-file-${file.path}`,
        group: 'Open file',
        label: file.path,
        onRun: () => {
          applyWorkspaceMutation({ type: 'select', path: file.path });
          setMobileView('source');
        },
      });
    }
  }
  commands.push({
    id: 'help-shortcuts',
    group: 'Help',
    label: 'Show keyboard shortcuts',
    hint: '?',
    onRun: () => setShortcutsHelpOpen(true),
  });

  const shortcuts: ShortcutEntry[] = [
    { keys: 'Ctrl/Cmd + K', description: 'Open the command palette' },
    { keys: 'Ctrl/Cmd + Shift + Enter', description: 'Validate' },
    { keys: 'Shift + Alt + F', description: 'Format' },
    { keys: 'Ctrl/Cmd + Enter', description: 'Generate' },
    { keys: '?', description: 'Show this keyboard shortcuts panel' },
    { keys: 'Esc', description: 'Close the command palette or this panel' },
  ];

  return (
    <main className="workbench" data-state={state.runtime} data-mobile-view={mobileView}>
      <WorkbenchHeader
        status={state.status}
        diagnosticLabel={diagnosticLabel}
        statusIsError={statusIsError}
        isWorking={state.runtime === 'working'}
        persistencePhase={persistentWorkspace.phase}
        languageStatus={languageStatus}
        themePreference={themePreference}
        resolvedTheme={resolvedTheme}
        onThemePreferenceChange={setThemePreference}
        onOpenCommandPalette={() => setCommandPaletteOpen(true)}
        onOpenShortcutsHelp={() => setShortcutsHelpOpen(true)}
      />
      <ShortcutsHelp
        open={shortcutsHelpOpen}
        shortcuts={shortcuts}
        onClose={() => setShortcutsHelpOpen(false)}
      />
      <CommandPalette
        open={commandPaletteOpen}
        commands={commands}
        onClose={() => setCommandPaletteOpen(false)}
      />
      <Toolbar
        runtime={state.runtime}
        compileTarget={state.compileTarget}
        actionsDisabled={actionsDisabled}
        languageCanRetry={languageCanRetry}
        persistencePhase={persistentWorkspace.phase}
        onExportSource={exportSource}
        onResetToDemo={handleResetToDemo}
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
            onCreate={(path) => {
              applyWorkspaceMutation({ type: 'create', path }, true);
              setMobileView('source');
            }}
            onImport={importWorkspaceFiles}
            onRename={(from, to) =>
              applyWorkspaceMutation({
                type: 'rename',
                from,
                to,
              }, true)
            }
            onDelete={(path) => {
              if (confirmReplace(`Delete workspace file ${path}?`)) {
                applyWorkspaceMutation({
                  type: 'delete',
                  path,
                }, true);
              }
            }}
            onSelect={(path) => {
              applyWorkspaceMutation({ type: 'select', path });
              setMobileView('source');
            }}
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
                selectedModel={selectedModel}
                onModelChange={setSelectedModel}
                models={models}
                onReset={handleAiReset}
                onAddModel={handleAiAddModel}
                onFetchModels={handleAiFetchModels}
                onProviderKindChange={handleAiProviderKindChange}
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
                pluginRegistry={pluginRegistry}
              />
            }
          />
        }
        bottom={
          <BottomPanel
            diagnosticsCount={state.diagnostics.length}
            compatibilityCount={compatibilityIssueCount}
            governanceCount={governanceFindingCount}
            diagnostics={
              <section
                className="diagnostics"
                aria-label="Document diagnostics"
                data-testid="diagnostics"
              >
                <h2>Diagnostics</h2>
                {state.diagnostics.length > 0 ? (
                  <ul>
                    {state.diagnostics.map((diagnostic, index) => {
                      const path = pathFromSourceUri(diagnostic.uri);
                      const positioned =
                        diagnostic.line !== null && diagnostic.column !== null;
                      const location = positioned
                        ? `${path}:${diagnostic.line}:${diagnostic.column}`
                        : path;
                      const body = (
                        <>
                          <span className="diagnostics__location">
                            {location}
                          </span>
                          <strong>{diagnostic.code}</strong>{' '}
                          {diagnostic.message}
                        </>
                      );
                      return (
                        <li key={`${diagnostic.code}-${index}`}>
                          {positioned ? (
                            <button
                              type="button"
                              className="diagnostics__item"
                              onClick={() => revealDiagnostic(diagnostic)}
                            >
                              {body}
                            </button>
                          ) : (
                            <span className="diagnostics__item">{body}</span>
                          )}
                        </li>
                      );
                    })}
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
