// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { WorkspaceFiles } from './WorkspaceFiles';
import type { PlaygroundWorkspace } from './workspace';

const workspace: PlaygroundWorkspace = {
  schemaVersion: 1,
  id: 'local',
  revision: 2,
  activeFile: 'b.mdl',
  files: [
    { path: 'b.mdl', content: 'domain b {}', version: 1 },
    { path: 'a.mdl', content: 'domain a {}', version: 1 },
  ],
};

afterEach(cleanup);

test('selects, creates, renames, and deletes workspace files', async () => {
  const user = userEvent.setup();
  const handlers = {
    onCreate: vi.fn(),
    onImport: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    onSelect: vi.fn(),
  };
  render(
    <WorkspaceFiles
      workspace={workspace}
      disabled={false}
      {...handlers}
    />,
  );

  await user.click(screen.getByRole('button', { name: 'a.mdl' }));
  expect(handlers.onSelect).toHaveBeenCalledWith('a.mdl');

  await user.type(screen.getByLabelText('Workspace file path'), 'new.mdl');
  await user.click(screen.getByRole('button', { name: 'New file' }));
  expect(handlers.onCreate).toHaveBeenCalledWith('new.mdl');

  await user.clear(screen.getByLabelText('Workspace file path'));
  await user.type(
    screen.getByLabelText('Workspace file path'),
    'renamed.mdl',
  );
  await user.click(screen.getByRole('button', { name: 'Rename active' }));
  expect(handlers.onRename).toHaveBeenCalledWith('renamed.mdl');

  await user.click(screen.getByRole('button', { name: 'Delete active' }));
  expect(handlers.onDelete).toHaveBeenCalledOnce();
  expect(screen.getByRole('list', { name: 'Workspace files' })).toBeTruthy();
  expect(screen.getByText('Active file')).toBeTruthy();
});

test('reports invalid paths and does not dispatch disabled controls', async () => {
  const user = userEvent.setup();
  const onCreate = vi.fn();
  const { rerender } = render(
    <WorkspaceFiles
      workspace={workspace}
      disabled={false}
      onCreate={onCreate}
      onImport={vi.fn()}
      onRename={vi.fn()}
      onDelete={vi.fn()}
      onSelect={vi.fn()}
    />,
  );

  await user.type(
    screen.getByLabelText('Workspace file path'),
    '../escape.mdl',
  );
  await user.click(screen.getByRole('button', { name: 'New file' }));
  expect(screen.getByRole('alert').textContent).toContain(
    'Choose a safe relative .mdl path',
  );
  expect(onCreate).not.toHaveBeenCalled();

  rerender(
    <WorkspaceFiles
      workspace={workspace}
      disabled
      onCreate={onCreate}
      onImport={vi.fn()}
      onRename={vi.fn()}
      onDelete={vi.fn()}
      onSelect={vi.fn()}
    />,
  );
  expect(
    (screen.getByRole('button', { name: 'New file' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole('button', {
        name: 'Delete active',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (screen.getByRole('button', { name: 'a.mdl' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
