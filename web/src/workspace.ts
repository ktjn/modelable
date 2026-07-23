import type { BrowserSource } from './protocol';

export const PLAYGROUND_WORKSPACE_SCHEMA_VERSION = 1 as const;

export interface PlaygroundFile {
  path: string;
  content: string;
  version: number;
}

export interface WorkspaceMetadata {
  lastAiAccept?: {
    provider: string;
    model: string;
    timestamp: number;
  };
}

export interface PlaygroundWorkspace {
  schemaVersion: typeof PLAYGROUND_WORKSPACE_SCHEMA_VERSION;
  id: string;
  revision: number;
  files: PlaygroundFile[];
  activeFile: string;
  metadata?: WorkspaceMetadata;
}

export type WorkspaceMutation =
  | { type: 'create'; path: string; content?: string }
  | { type: 'update'; path: string; content: string }
  | { type: 'rename'; from: string; to: string }
  | { type: 'delete'; path: string }
  | { type: 'select'; path: string };

export type WorkspaceValidationReason = 'invalid' | 'incompatible';

export class WorkspaceValidationError extends Error {
  constructor(
    readonly reason: WorkspaceValidationReason,
    message: string,
  ) {
    super(message);
    this.name = 'WorkspaceValidationError';
  }
}

const controlCharacters =
  /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/u;
const urlScheme = /^[A-Za-z][A-Za-z0-9+.-]*:/u;

export function normalizeWorkspacePath(path: string): string {
  const normalized = path.replaceAll('\\', '/');
  const segments = normalized.split('/');
  if (
    normalized.length === 0 ||
    normalized.startsWith('/') ||
    urlScheme.test(normalized) ||
    controlCharacters.test(normalized) ||
    !normalized.endsWith('.mdl') ||
    segments.some(
      (segment) =>
        segment.length === 0 || segment === '.' || segment === '..',
    )
  ) {
    throw new WorkspaceValidationError(
      'invalid',
      'Choose a safe relative .mdl path',
    );
  }
  return normalized;
}

export function createDefaultWorkspace(
  defaultSource: string,
  id = 'local',
): PlaygroundWorkspace {
  return {
    schemaVersion: PLAYGROUND_WORKSPACE_SCHEMA_VERSION,
    id,
    revision: 1,
    files: [{ path: 'main.mdl', content: defaultSource, version: 1 }],
    activeFile: 'main.mdl',
  };
}

export function mutateWorkspace(
  workspace: PlaygroundWorkspace,
  mutation: WorkspaceMutation,
): PlaygroundWorkspace {
  const revision = workspace.revision + 1;
  switch (mutation.type) {
    case 'create': {
      const path = normalizeWorkspacePath(mutation.path);
      ensureMissing(workspace, path);
      return {
        ...workspace,
        revision,
        files: [
          ...workspace.files,
          { path, content: mutation.content ?? '', version: 1 },
        ],
        activeFile: path,
      };
    }
    case 'update': {
      const path = normalizeWorkspacePath(mutation.path);
      const file = findFile(workspace, path);
      return {
        ...workspace,
        revision,
        files: workspace.files.map((candidate) =>
          candidate.path === path
            ? {
                ...file,
                content: mutation.content,
                version: file.version + 1,
              }
            : candidate,
        ),
      };
    }
    case 'rename': {
      const from = normalizeWorkspacePath(mutation.from);
      const to = normalizeWorkspacePath(mutation.to);
      const file = findFile(workspace, from);
      if (from === to) {
        throw invalidWorkspace('Choose a different file path');
      }
      ensureMissing(workspace, to);
      return {
        ...workspace,
        revision,
        files: workspace.files.map((candidate) =>
          candidate.path === from
            ? { ...file, path: to, version: file.version + 1 }
            : candidate,
        ),
        activeFile: workspace.activeFile === from ? to : workspace.activeFile,
      };
    }
    case 'delete': {
      const path = normalizeWorkspacePath(mutation.path);
      findFile(workspace, path);
      if (workspace.files.length === 1) {
        throw invalidWorkspace('A workspace must contain at least one file');
      }
      const files = workspace.files.filter((file) => file.path !== path);
      return {
        ...workspace,
        revision,
        files,
        activeFile:
          workspace.activeFile === path
            ? [...files].sort(compareFiles)[0]!.path
            : workspace.activeFile,
      };
    }
    case 'select': {
      const path = normalizeWorkspacePath(mutation.path);
      findFile(workspace, path);
      return { ...workspace, revision, activeFile: path };
    }
  }
}

export function mutateWorkspaceBatch(
  workspace: PlaygroundWorkspace,
  mutations: WorkspaceMutation[],
): PlaygroundWorkspace {
  return mutations.reduce(mutateWorkspace, workspace);
}

export function parseWorkspaceRecord(value: unknown): PlaygroundWorkspace {
  if (!isRecord(value)) {
    throw invalidWorkspace('Stored workspace must be an object');
  }
  if (
    Object.hasOwn(value, 'schemaVersion') &&
    value.schemaVersion !== PLAYGROUND_WORKSPACE_SCHEMA_VERSION
  ) {
    throw new WorkspaceValidationError(
      'incompatible',
      'Stored workspace uses an unsupported schema version',
    );
  }
  requireExactKeys(value, [
    'schemaVersion',
    'id',
    'revision',
    'files',
    'activeFile',
  ]);
  if (
    typeof value.id !== 'string' ||
    value.id.length === 0 ||
    !isPositiveInteger(value.revision) ||
    !Array.isArray(value.files) ||
    value.files.length === 0 ||
    typeof value.activeFile !== 'string'
  ) {
    throw invalidWorkspace('Stored workspace is incomplete');
  }

  const files = value.files.map((candidate): PlaygroundFile => {
    if (!isRecord(candidate)) {
      throw invalidWorkspace('Stored workspace contains an invalid file');
    }
    requireExactKeys(candidate, ['path', 'content', 'version']);
    if (
      typeof candidate.path !== 'string' ||
      typeof candidate.content !== 'string' ||
      !isPositiveInteger(candidate.version)
    ) {
      throw invalidWorkspace('Stored workspace contains an invalid file');
    }
    return {
      path: normalizeWorkspacePath(candidate.path),
      content: candidate.content,
      version: candidate.version,
    };
  });

  const paths = new Set(files.map((file) => file.path));
  if (paths.size !== files.length) {
    throw invalidWorkspace('Stored workspace contains duplicate paths');
  }
  const activeFile = normalizeWorkspacePath(value.activeFile);
  if (!paths.has(activeFile)) {
    throw invalidWorkspace('Stored active file does not exist');
  }

  return {
    schemaVersion: PLAYGROUND_WORKSPACE_SCHEMA_VERSION,
    id: value.id,
    revision: value.revision,
    files,
    activeFile,
  };
}

export function workspaceSources(
  workspace: PlaygroundWorkspace,
): BrowserSource[] {
  return [...workspace.files].sort(compareFiles).map((file) => ({
    uri: sourceUri(file.path),
    text: file.content,
    version: file.version,
  }));
}

function invalidWorkspace(message: string): WorkspaceValidationError {
  return new WorkspaceValidationError('invalid', message);
}

function findFile(
  workspace: PlaygroundWorkspace,
  path: string,
): PlaygroundFile {
  const file = workspace.files.find((candidate) => candidate.path === path);
  if (file === undefined) {
    throw invalidWorkspace(`Workspace file does not exist: ${path}`);
  }
  return file;
}

function ensureMissing(workspace: PlaygroundWorkspace, path: string): void {
  if (workspace.files.some((file) => file.path === path)) {
    throw invalidWorkspace(`Workspace file already exists: ${path}`);
  }
}

function compareFiles(left: PlaygroundFile, right: PlaygroundFile): number {
  return left.path.localeCompare(right.path);
}

function sourceUri(path: string): string {
  return `file:///${path.split('/').map(encodeURIComponent).join('/')}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireExactKeys(
  value: Record<string, unknown>,
  expected: string[],
): void {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  if (
    actual.length !== sortedExpected.length ||
    actual.some((key, index) => key !== sortedExpected[index])
  ) {
    throw invalidWorkspace('Stored workspace contains unexpected fields');
  }
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && typeof value === 'number' && value > 0;
}
