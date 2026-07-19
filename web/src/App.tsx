import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from 'react';

import { appReducer, initialAppState } from './app-state';
import {
  BrowserCompilerClient,
  BrowserCompilerError,
  type BrowserCompilerClientLike,
} from './client';
import { normalizeDiagnostics } from './diagnostics';
import initialSource from './example.mdl?raw';
import { ArtifactEditor } from './editor/ArtifactEditor';
import { SourceEditor } from './editor/SourceEditor';
import type { SourceEditorHandle } from './editor/types';
import {
  downloadText,
  readSourceFile,
  sanitizeDownloadName,
} from './files';

const SOURCE_URI = 'file:///main.mdl';
const createBrowserCompilerClient = (): BrowserCompilerClientLike =>
  new BrowserCompilerClient();
const performanceNow = (): number => performance.now();
const sourceFileErrorMessages = new Set([
  'Choose a .mdl or .txt source file',
  'Source files must be 1 MiB or smaller',
]);

export interface AppProps {
  createClient?: () => BrowserCompilerClientLike;
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

function sourceFileErrorMessage(error: unknown): string {
  if (
    error instanceof Error &&
    sourceFileErrorMessages.has(error.message)
  ) {
    return error.message;
  }
  return 'Could not read the selected source file. Try another .mdl or .txt file.';
}

export function App({
  createClient = createBrowserCompilerClient,
  now = performanceNow,
  confirmReplace = globalThis.confirm,
  download = downloadText,
}: AppProps) {
  const [state, dispatch] = useReducer(appReducer, initialAppState);
  const [clientAttempt, setClientAttempt] = useState(0);
  const [fileError, setFileError] = useState<string | null>(null);
  const [statusIsError, setStatusIsError] = useState(false);
  const sourceEditorRef = useRef<SourceEditorHandle>(null);
  const sourceFileInputRef = useRef<HTMLInputElement>(null);
  const clientRef = useRef<BrowserCompilerClientLike>(null);
  const operationPendingRef = useRef(false);
  const recoveryPendingRef = useRef(false);
  const importAttemptRef = useRef(0);
  const revisionRef = useRef(initialAppState.revision);
  const cleanSourceRef = useRef(initialSource);
  const sourceFilenameRef = useRef('main.mdl');

  useEffect(
    () => () => {
      importAttemptRef.current += 1;
    },
    [],
  );

  useEffect(() => {
    const client = createClient();
    const startedAt = now();
    clientRef.current = client;
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
      if (clientRef.current !== client) {
        return;
      }
      clientRef.current = null;
      client.dispose();
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

      const source = sourceEditor.getSource();
      const revision = source.version;
      const startedAt = now();
      operationPendingRef.current = true;
      setStatusIsError(false);
      dispatch({ type: 'operationStarted', operation, revision });

      try {
        if (operation === 'validate') {
          const result = await client.openWorkspace([source]);
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
          const result = await client.formatSource(source);
          if (
            result.replacement_text !== null &&
            !hasErrorDiagnostics(result.diagnostics) &&
            revisionRef.current === revision
          ) {
            sourceEditor.applyFormattedText(result.replacement_text);
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

        const result = await client.compileJsonSchema([source]);
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
    const client = clientRef.current;
    clientRef.current = null;
    client?.dispose();
    operationPendingRef.current = false;
    setStatusIsError(false);
    dispatch({ type: 'retryRequested' });
    setClientAttempt((attempt) => attempt + 1);
  };

  const importSourceFile = async (
    input: HTMLInputElement,
  ): Promise<void> => {
    const file = input.files?.[0];
    if (file === undefined) {
      return;
    }
    const attempt = importAttemptRef.current + 1;
    importAttemptRef.current = attempt;
    try {
      const imported = await readSourceFile(file);
      if (importAttemptRef.current !== attempt) {
        return;
      }
      const sourceEditor = sourceEditorRef.current;
      if (sourceEditor === null) {
        return;
      }
      const currentText = sourceEditor.getSource().text;
      if (
        currentText !== cleanSourceRef.current &&
        !confirmReplace(
          'Replace the current source and discard unsaved changes?',
        )
      ) {
        return;
      }
      cleanSourceRef.current = imported.text;
      sourceFilenameRef.current = imported.name;
      sourceEditor.replaceText(imported.text);
      sourceEditor.focus();
      setFileError(null);
    } catch (error: unknown) {
      if (importAttemptRef.current === attempt) {
        setFileError(sourceFileErrorMessage(error));
      }
    } finally {
      input.value = '';
    }
  };

  const exportSource = (): void => {
    const source = sourceEditorRef.current?.getSource();
    if (source === undefined) {
      return;
    }
    download(
      source.text,
      sanitizeDownloadName(sourceFilenameRef.current, '.mdl'),
      'text/plain',
    );
    cleanSourceRef.current = source.text;
  };

  const normalizedDiagnostics = normalizeDiagnostics(
    state.diagnostics,
    SOURCE_URI,
  );
  const selectedArtifact =
    state.artifacts.find(
      (artifact) => artifact.path === state.selectedArtifactPath,
    ) ?? null;
  const artifactIsStale =
    state.artifacts.length > 0 &&
    state.artifactRevision !== state.revision;
  const actionsDisabled = state.runtime !== 'ready';
  const diagnosticLabel = `${state.diagnostics.length} ${
    state.diagnostics.length === 1 ? 'diagnostic' : 'diagnostics'
  }`;

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
        </div>
      </header>
      <nav className="toolbar" aria-label="Playground actions">
        <input
          ref={sourceFileInputRef}
          type="file"
          accept=".mdl,.txt,text/plain"
          hidden
          onChange={(event) =>
            void importSourceFile(event.currentTarget)
          }
        />
        <button
          type="button"
          onClick={() => sourceFileInputRef.current?.click()}
        >
          Import
        </button>
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
      </nav>
      {fileError === null ? null : (
        <p className="error-label" role="alert">
          File error: {fileError}
        </p>
      )}
      <section className="workspace" aria-label="Single-file workspace">
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
          <SourceEditor
            ref={sourceEditorRef}
            initialValue={initialSource}
            markers={normalizedDiagnostics.markers}
            onRevisionChange={(revision) => {
              revisionRef.current = revision;
              setStatusIsError(false);
              dispatch({ type: 'revisionChanged', revision });
            }}
          />
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
      <footer className="metrics-strip" data-testid="metrics">
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
