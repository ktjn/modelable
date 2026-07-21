import type { BrowserArtifact, BrowserDiagnostic } from './protocol';
import {
  mutateWorkspace,
  type PlaygroundWorkspace,
  type WorkspaceMutation,
} from './workspace';

export type RuntimePhase = 'loading' | 'ready' | 'working' | 'failed';
export type CompilerOperation = 'validate' | 'format' | 'generate';

export interface AppState {
  runtime: RuntimePhase;
  operation: CompilerOperation | null;
  revision: number;
  diagnostics: BrowserDiagnostic[];
  artifacts: BrowserArtifact[];
  selectedArtifactPath: string | null;
  artifactRevision: number | null;
  status: string;
  initializationDuration: number | null;
  lastOperationDuration: number | null;
}

export const initialAppState: AppState = {
  runtime: 'loading',
  operation: null,
  revision: 1,
  diagnostics: [],
  artifacts: [],
  selectedArtifactPath: null,
  artifactRevision: null,
  status: 'Initializing compiler…',
  initializationDuration: null,
  lastOperationDuration: null,
};

export type AppAction =
  | { type: 'initialized'; duration: number }
  | {
      type: 'runtimeFailed';
      message: string;
      duration: number | null;
      operation?: CompilerOperation;
      revision?: number;
    }
  | { type: 'retryRequested' }
  | { type: 'revisionChanged'; revision: number }
  | {
      type: 'operationStarted';
      operation: CompilerOperation;
      revision: number;
    }
  | {
      type: 'operationSucceeded';
      operation: CompilerOperation;
      revision: number;
      diagnostics: BrowserDiagnostic[];
      artifacts?: BrowserArtifact[];
      duration: number;
    }
  | {
      type: 'operationFailed';
      operation: CompilerOperation;
      revision: number;
      message: string;
      diagnostics?: BrowserDiagnostic[];
      duration: number;
    }
  | {
      type: 'liveDiagnosticsPublished';
      revision: number;
      diagnostics: BrowserDiagnostic[];
    }
  | { type: 'artifactSelected'; path: string };

export type WorkspaceAppState = Omit<AppState, 'revision'> & {
  workspace: PlaygroundWorkspace;
};

export type WorkspaceAppAction =
  | AppAction
  | { type: 'workspaceReplaced'; workspace: PlaygroundWorkspace }
  | { type: 'workspaceMutated'; mutation: WorkspaceMutation };

const operationLabels: Record<CompilerOperation, string> = {
  validate: 'Validation',
  format: 'Formatting',
  generate: 'Generation',
};

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'initialized':
      return {
        ...state,
        runtime: 'ready',
        operation: null,
        status: 'Compiler ready',
        initializationDuration: action.duration,
      };
    case 'runtimeFailed':
      return {
        ...state,
        runtime: 'failed',
        operation: null,
        artifactRevision:
          action.operation === 'generate' &&
          action.revision === state.revision
            ? null
            : state.artifactRevision,
        status: action.message,
        initializationDuration:
          state.runtime === 'loading'
            ? action.duration
            : state.initializationDuration,
        lastOperationDuration:
          state.runtime === 'working'
            ? action.duration
            : state.lastOperationDuration,
      };
    case 'retryRequested':
      return {
        ...state,
        runtime: 'loading',
        operation: null,
        status: 'Initializing compiler…',
        initializationDuration: null,
      };
    case 'revisionChanged':
      return {
        ...state,
        revision: action.revision,
        diagnostics: [],
        status: 'Source changed',
      };
    case 'operationStarted':
      if (state.runtime !== 'ready') {
        return state;
      }
      return {
        ...state,
        runtime: 'working',
        operation: action.operation,
        status: `${operationLabels[action.operation]} in progress…`,
      };
    case 'operationSucceeded': {
      const completed = {
        ...state,
        runtime: 'ready' as const,
        operation: null,
        status: `${operationLabels[action.operation]} complete`,
        lastOperationDuration: action.duration,
      };
      if (action.revision !== state.revision) {
        return completed;
      }
      if (action.artifacts === undefined) {
        return { ...completed, diagnostics: action.diagnostics };
      }
      return {
        ...completed,
        diagnostics: action.diagnostics,
        artifacts: action.artifacts,
        selectedArtifactPath: action.artifacts[0]?.path ?? null,
        artifactRevision: action.revision,
      };
    }
    case 'operationFailed':
      return {
        ...state,
        runtime: 'ready',
        operation: null,
        artifactRevision:
          action.operation === 'generate' &&
          action.revision === state.revision
            ? null
            : state.artifactRevision,
        diagnostics:
          action.revision === state.revision &&
          action.diagnostics !== undefined
            ? action.diagnostics
            : state.diagnostics,
        status: action.message,
        lastOperationDuration: action.duration,
      };
    case 'liveDiagnosticsPublished':
      if (action.revision !== state.revision) {
        return state;
      }
      return {
        ...state,
        diagnostics: action.diagnostics,
      };
    case 'artifactSelected':
      if (!state.artifacts.some((artifact) => artifact.path === action.path)) {
        return state;
      }
      return { ...state, selectedArtifactPath: action.path };
  }
}

export function workspaceAppReducer(
  state: WorkspaceAppState,
  action: WorkspaceAppAction,
): WorkspaceAppState {
  if (action.type === 'workspaceReplaced') {
    return invalidateDerivedWorkspaceState(state, action.workspace);
  }
  if (action.type === 'workspaceMutated') {
    return invalidateDerivedWorkspaceState(
      state,
      mutateWorkspace(state.workspace, action.mutation),
    );
  }

  const reduced = appReducer(
    { ...state, revision: state.workspace.revision },
    action,
  );
  const { revision: _revision, ...workspaceState } = reduced;
  return { ...workspaceState, workspace: state.workspace };
}

function invalidateDerivedWorkspaceState(
  state: WorkspaceAppState,
  workspace: PlaygroundWorkspace,
): WorkspaceAppState {
  return {
    ...state,
    workspace,
    diagnostics: [],
    artifacts: [],
    selectedArtifactPath: null,
    artifactRevision: null,
    status: 'Source changed',
  };
}
