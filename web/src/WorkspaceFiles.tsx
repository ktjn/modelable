import { useRef, useState } from 'react';

import {
  readWorkspaceFiles,
  type ImportedWorkspaceFile,
} from './files';
import {
  normalizeWorkspacePath,
  type PlaygroundWorkspace,
} from './workspace';

export interface WorkspaceFilesProps {
  workspace: PlaygroundWorkspace;
  disabled: boolean;
  onCreate(path: string): void;
  onImport(files: ImportedWorkspaceFile[]): void;
  onRename(path: string): void;
  onDelete(): void;
  onSelect(path: string): void;
}

export function WorkspaceFiles({
  workspace,
  disabled,
  onCreate,
  onImport,
  onRename,
  onDelete,
  onSelect,
}: WorkspaceFilesProps) {
  const [path, setPath] = useState('');
  const [error, setError] = useState<string | null>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  const runPathAction = (action: (normalizedPath: string) => void): void => {
    try {
      const normalizedPath = normalizeWorkspacePath(path);
      action(normalizedPath);
      setPath('');
      setError(null);
    } catch (actionError: unknown) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : 'Could not update the workspace file',
      );
    }
  };

  const importFiles = async (input: HTMLInputElement): Promise<void> => {
    try {
      const files = await readWorkspaceFiles(input.files ?? []);
      if (files.length > 0) {
        onImport(files);
      }
      setError(null);
    } catch (importError: unknown) {
      setError(
        importError instanceof Error
          ? importError.message
          : 'Could not import the workspace files',
      );
    } finally {
      input.value = '';
    }
  };

  return (
    <aside className="workspace-files" aria-label="Workspace file controls">
      <div className="workspace-files-heading">
        <p className="workspace-files-label">Workspace index</p>
        <p className="workspace-files-count">
          {workspace.files.length}{' '}
          {workspace.files.length === 1 ? 'file' : 'files'}
        </p>
      </div>
      <ul className="workspace-file-list" aria-label="Workspace files">
        {[...workspace.files]
          .sort((left, right) => left.path.localeCompare(right.path))
          .map((file) => {
            const active = file.path === workspace.activeFile;
            return (
              <li key={file.path}>
                <button
                  type="button"
                  className="workspace-file"
                  aria-current={active ? 'true' : undefined}
                  disabled={disabled}
                  onClick={() => onSelect(file.path)}
                >
                  {file.path}
                </button>
                {active ? (
                  <span className="active-file-label">Active file</span>
                ) : null}
              </li>
            );
          })}
      </ul>
      <div className="workspace-file-actions">
        <label htmlFor="workspace-file-path">Workspace file path</label>
        <input
          id="workspace-file-path"
          value={path}
          disabled={disabled}
          placeholder="customer.mdl"
          spellCheck={false}
          onChange={(event) => setPath(event.target.value)}
        />
        <div className="workspace-file-action-grid">
          <button
            type="button"
            disabled={disabled}
            onClick={() => runPathAction(onCreate)}
          >
            New file
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => runPathAction(onRename)}
          >
            Rename active
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => importInputRef.current?.click()}
          >
            Import files
          </button>
          <button
            type="button"
            disabled={disabled || workspace.files.length === 1}
            onClick={onDelete}
          >
            Delete active
          </button>
        </div>
        <input
          ref={importInputRef}
          type="file"
          accept=".mdl"
          multiple
          hidden
          disabled={disabled}
          aria-label="Import workspace files"
          onChange={(event) => void importFiles(event.currentTarget)}
        />
      </div>
      {error === null ? null : (
        <p className="workspace-file-error" role="alert">
          {error}
        </p>
      )}
    </aside>
  );
}
