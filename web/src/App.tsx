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
          dispatch({ type: 'initialized', duration: now() - startedAt });
        }
      },
      (error: unknown) => {
        if (clientRef.current === client) {
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
          return;
        }

        const result = await client.compileJsonSchema([source]);
        const duration = now() - startedAt;
        if (
          hasErrorDiagnostics(result.diagnostics) ||
          result.artifacts.length === 0
        ) {
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

  const retryCompiler = (): void => {
    const client = clientRef.current;
    clientRef.current = null;
    client?.dispose();
    operationPendingRef.current = false;
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
    <main className="workbench">
      <header className="workbench-header">
        <div>
          <p className="eyebrow">Local schema workbench</p>
          <h1>Modelable playground</h1>
        </div>
        <p role="status" aria-live="polite">
          {state.status} · {diagnosticLabel}
        </p>
        <p className="timings">
          {state.initializationDuration === null
            ? null
            : `Initialized in ${state.initializationDuration.toFixed(0)} ms`}
          {state.lastOperationDuration === null
            ? null
            : ` · Last operation ${state.lastOperationDuration.toFixed(0)} ms`}
        </p>
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
          onClick={() => void runOperation('validate')}
        >
          Validate
        </button>
        <button
          type="button"
          disabled={actionsDisabled}
          onClick={() => void runOperation('format')}
        >
          Format
        </button>
        <button
          type="button"
          disabled={actionsDisabled}
          onClick={() => void runOperation('generate')}
        >
          Generate
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
      {fileError === null ? null : <p role="alert">{fileError}</p>}
      <section className="workspace" aria-label="Single-file workspace">
        <section id="source-editor" aria-label="Modelable source" tabIndex={-1}>
          <SourceEditor
            ref={sourceEditorRef}
            initialValue={initialSource}
            markers={normalizedDiagnostics.markers}
            onRevisionChange={(revision) => {
              revisionRef.current = revision;
              dispatch({ type: 'revisionChanged', revision });
            }}
          />
        </section>
        <section aria-label="Generated JSON Schema">
          {state.artifacts.length > 1 ? (
            <label>
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
          {artifactIsStale ? (
            <p>Stale—source changed after generation</p>
          ) : null}
          <ArtifactEditor value={selectedArtifact?.content ?? ''} />
        </section>
      </section>
      {normalizedDiagnostics.documentDiagnostics.length > 0 ? (
        <section aria-label="Document diagnostics">
          <ul>
            {normalizedDiagnostics.documentDiagnostics.map(
              (diagnostic, index) => (
                <li key={`${diagnostic.code}-${index}`}>
                  {diagnostic.message}
                </li>
              ),
            )}
          </ul>
        </section>
      ) : null}
    </main>
  );
}
