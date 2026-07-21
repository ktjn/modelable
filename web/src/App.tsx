import {
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
} from './client';
import { normalizeDiagnosticsByUri } from './diagnostics';
import initialSource from './example.mdl?raw';
import { ArtifactEditor } from './editor/ArtifactEditor';
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
import { GraphPanelContainer } from './visualization/GraphPanelContainer';
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
    createDefaultWorkspace(initialSource),
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
  const [mobileView, setMobileView] = useState<'source' | 'graph'>('source');
  const [graphCollapsed, setGraphCollapsed] = useState(true);
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

        const result = await client.compileJsonSchema(sources);
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
    [now, state.runtime],
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

  return (
    <main className="workbench" data-state={state.runtime}>
      <header className="workbench-header">
        <div>
          <p className="eyebrow">Local schema workbench</p>
          <h1>Modelable playground</h1>
        </div>
        <div className="state-block">
          <span className="state-signal" aria-hidden="true" />
          <p
            className="status"
            role={statusIsError ? 'alert' : 'status'}
            aria-live={statusIsError ? 'assertive' : 'polite'}
          >
            {state.status} · {diagnosticLabel}
          </p>
          <p className="persistence-status" aria-live="polite">
            {persistentWorkspace.phase === 'saved'
              ? 'Saved locally'
              : persistentWorkspace.phase === 'saving'
                ? 'Saving locally…'
                : 'Storage unavailable · changes remain in this tab'}
          </p>
          <p className="persistence-status" aria-live="polite">
            {languageStatus}
          </p>
        </div>
      </header>
      <nav className="toolbar" aria-label="Playground actions">
        <button type="button" onClick={exportSource}>
          Export source
        </button>
        <button
          type="button"
          disabled={actionsDisabled}
          aria-keyshortcuts="Control+Shift+Enter Meta+Shift+Enter"
          onClick={handleValidate}
        >
          Validate
        </button>
        <button
          type="button"
          disabled={actionsDisabled}
          aria-keyshortcuts="Shift+Alt+F"
          onClick={handleFormat}
        >
          Format
        </button>
        <button
          type="button"
          disabled={actionsDisabled}
          aria-keyshortcuts="Control+Enter Meta+Enter"
          onClick={handleGenerate}
        >
          Generate JSON Schema
        </button>
        <button
          type="button"
          disabled={selectedArtifact === null}
          onClick={() => {
            if (selectedArtifact === null) {
              return;
            }
            download(
              selectedArtifact.content,
              sanitizeDownloadName(selectedArtifact.path, '.json'),
              selectedArtifact.media_type,
            );
          }}
        >
          Export artifact
        </button>
        {state.runtime === 'failed' ? (
          <button type="button" onClick={retryCompiler}>
            Retry compiler
          </button>
        ) : null}
        {state.runtime !== 'failed' && languageCanRetry ? (
          <button
            type="button"
            onClick={() => {
              setLanguageStatus('Retrying language services…');
              setLanguageCanRetry(false);
              void languageControllerRef.current?.retry();
            }}
          >
            Retry language services
          </button>
        ) : null}
        {persistentWorkspace.phase === 'memory-only' ? (
          <button
            type="button"
            onClick={() => void persistentWorkspace.retry()}
          >
            Retry storage
          </button>
        ) : null}
      </nav>
      <nav className="view-tabs" aria-label="View">
        <button
          type="button"
          className={`view-tab${mobileView === 'source' ? ' view-tab--active' : ''}`}
          aria-pressed={mobileView === 'source'}
          onClick={() => setMobileView('source')}
        >
          Source
        </button>
        <button
          type="button"
          className={`view-tab${mobileView === 'graph' ? ' view-tab--active' : ''}`}
          aria-pressed={mobileView === 'graph'}
          onClick={() => setMobileView('graph')}
        >
          Graph
        </button>
      </nav>
      <section
        className={`workspace${mobileView === 'graph' ? ' workspace--mobile-hidden' : ''}`}
        aria-label="Modelable workspace"
      >
        <section
          className="source-pane"
          id="source-editor"
          aria-label="Modelable source"
          tabIndex={-1}
          onFocus={(event) => {
            if (event.target === event.currentTarget) {
              sourceEditorRef.current?.focus();
            }
          }}
        >
          <div className="pane-heading">
            <div>
              <p className="pane-index">Source 01</p>
              <h2>Modelable source</h2>
            </div>
            <p className="local-note">Runs locally in this browser</p>
          </div>
          <div className="source-workspace">
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
          </div>
          <section
            className="diagnostics"
            aria-label="Document diagnostics"
            data-testid="diagnostics"
          >
            <h3>Diagnostics</h3>
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
        </section>
        <section
          className="artifact-pane"
          aria-label="Generated JSON Schema"
          data-testid="artifacts"
        >
          <div className="pane-heading">
            <div>
              <p className="pane-index">Artifact 02</p>
              <h2>Generated JSON Schema</h2>
            </div>
            {artifactIsStale ? (
              <p className="stale-label">
                Stale—source changed after generation
              </p>
            ) : (
              <p className="fresh-label">
                {selectedArtifact === null ? 'No artifact yet' : 'Current'}
              </p>
            )}
          </div>
          {state.artifacts.length > 1 ? (
            <label className="artifact-picker">
              Artifact
              <select
                value={state.selectedArtifactPath ?? ''}
                onChange={(event) =>
                  dispatch({
                    type: 'artifactSelected',
                    path: event.target.value,
                  })
                }
              >
                {state.artifacts.map((artifact) => (
                  <option key={artifact.path} value={artifact.path}>
                    {artifact.path}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <ArtifactEditor value={selectedArtifact?.content ?? ''} />
        </section>
      </section>
      <section
        className={`graph-pane${mobileView === 'source' ? ' graph-pane--mobile-hidden' : ''}${graphCollapsed ? ' graph-pane--collapsed' : ''}`}
        aria-label="Model graph visualization"
        data-testid="graph"
      >
        <div className="pane-heading">
          <div>
            <p className="pane-index">Graph 03</p>
            <h2>Model graph</h2>
          </div>
          <button
            type="button"
            className="graph-pane__toggle"
            aria-expanded={!graphCollapsed}
            onClick={() => setGraphCollapsed((collapsed) => !collapsed)}
          >
            {graphCollapsed ? 'Show graph' : 'Hide graph'}
          </button>
        </div>
        {mobileView === 'graph' || !graphCollapsed ? (
          <GraphPanelContainer
            clientRef={clientRef}
            runtimeReady={state.runtime === 'ready'}
            workspaceRevisionRef={workspaceRevisionRef}
          />
        ) : null}
      </section>
      <footer
        className="metrics-strip"
        data-testid="metrics"
        data-initialization-duration-ms={
          state.initializationDuration ?? undefined
        }
      >
        <p className="metrics-label">Browser compiler timing</p>
        <p className="timings">
          Initialization{' '}
          {state.initializationDuration === null
            ? 'pending'
            : `${state.initializationDuration.toFixed(1)} ms`}
          {' · '}Operation{' '}
          {state.lastOperationDuration === null
            ? 'not run'
            : `${state.lastOperationDuration.toFixed(1)} ms`}
        </p>
        <p className="privacy-note">No source leaves this page</p>
      </footer>
    </main>
  );
}
