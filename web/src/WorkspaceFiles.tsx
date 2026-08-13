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
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState('');
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

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

  const submitCreate = (): void => {
    try {
      const path = normalizeWorkspacePath(createName);
      onCreate(path);
      setCreating(false);
      setCreateName('');
      setError(null);
    } catch (createError: unknown) {
      setError(
        createError instanceof Error
          ? createError.message
          : 'Could not create file',
      );
    }
  };

  const submitRename = (): void => {
    if (renamingPath === null) return;
    try {
      const path = normalizeWorkspacePath(renameValue);
      if (path !== renamingPath) {
        onRename(path);
      }
      setRenamingPath(null);
      setRenameValue('');
      setError(null);
    } catch (renameError: unknown) {
      setError(
        renameError instanceof Error
          ? renameError.message
          : 'Could not rename file',
      );
    }
  };

  return (
    <aside className="workspace-files" aria-label="Workspace files">
      <div className="workspace-files__header">
        <div>
          <span className="workspace-files__eyebrow">Workspace</span>
          <span className="workspace-files__title">Model files</span>
        </div>
        <div className="workspace-files__actions">
          <button
            type="button"
            className="workspace-files__action"
            title="New file"
            aria-label="New file"
            disabled={disabled || creating}
            onClick={() => {
              setCreating(true);
              setCreateName('');
            }}
          >
            <span aria-hidden="true">+</span>
            <span>New</span>
          </button>
          <button
            type="button"
            className="workspace-files__action"
            title="Import files"
            aria-label="Import files"
            disabled={disabled}
            onClick={() => importInputRef.current?.click()}
          >
            <span aria-hidden="true">↑</span>
            <span>Import</span>
          </button>
        </div>
      </div>

      {creating ? (
        <div className="workspace-files__create">
          <input
            autoFocus
            value={createName}
            placeholder="file.mdl"
            spellCheck={false}
            disabled={disabled}
            onChange={(event) => setCreateName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submitCreate();
              else if (event.key === 'Escape') setCreating(false);
            }}
          />
          <button type="button" onClick={submitCreate}>
            Add
          </button>
        </div>
      ) : null}

      <ul className="workspace-file-list" aria-label="Workspace files">
        {[...workspace.files]
          .sort((left, right) => left.path.localeCompare(right.path))
          .map((file) => {
            const active = file.path === workspace.activeFile;
            const renaming = renamingPath === file.path;

            if (renaming) {
              return (
                <li key={file.path} className="workspace-file-item">
                  <input
                    autoFocus
                    className="workspace-file-item__rename"
                    value={renameValue}
                    spellCheck={false}
                    disabled={disabled}
                    onChange={(event) => setRenameValue(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') submitRename();
                      else if (event.key === 'Escape') setRenamingPath(null);
                    }}
                    onBlur={submitRename}
                  />
                </li>
              );
            }

            return (
              <li
                key={file.path}
                className={`workspace-file-item${
                  active ? ' workspace-file-item--active' : ''
                }`}
              >
                <button
                  type="button"
                  className="workspace-file-item__name"
                  aria-current={active ? 'true' : undefined}
                  disabled={disabled}
                  onClick={() => onSelect(file.path)}
                >
                  {file.path}
                </button>
                {active ? (
                  <span className="workspace-file-item__actions">
                    <button
                      type="button"
                      className="workspace-files__icon"
                      title="Rename"
                      aria-label="Rename"
                      disabled={disabled}
                      onClick={() => {
                        setRenamingPath(file.path);
                        setRenameValue(file.path);
                      }}
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      className="workspace-files__icon workspace-files__icon--danger"
                      title="Delete"
                      aria-label="Delete"
                      disabled={disabled || workspace.files.length === 1}
                      onClick={onDelete}
                    >
                      ✕
                    </button>
                  </span>
                ) : null}
              </li>
            );
          })}
      </ul>

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
      {error === null ? null : (
        <p className="workspace-file-error" role="alert">
          {error}
        </p>
      )}
    </aside>
  );
}
