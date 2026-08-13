// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
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

function chooseFiles(files: File[]): void {
  const input = screen.getByLabelText<HTMLInputElement>(
    'Import workspace files',
  );
  fireEvent.change(input, { target: { files } });
}

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

  await user.click(screen.getByRole('button', { name: 'New file' }));
  await user.type(screen.getByPlaceholderText('file.mdl'), 'new.mdl');
  await user.click(screen.getByRole('button', { name: 'Add' }));
  expect(handlers.onCreate).toHaveBeenCalledWith('new.mdl');

  await user.click(screen.getByRole('button', { name: 'b.mdl actions' }));
  await user.click(screen.getByRole('menuitem', { name: 'Rename' }));
  const renameInput = screen.getByDisplayValue('b.mdl');
  await user.clear(renameInput);
  await user.type(renameInput, 'renamed.mdl');
  await user.keyboard('{Enter}');
  expect(handlers.onRename).toHaveBeenCalledWith('b.mdl', 'renamed.mdl');

  await user.click(screen.getByRole('button', { name: 'a.mdl actions' }));
  await user.click(screen.getByRole('menuitem', { name: 'Delete' }));
  expect(handlers.onDelete).toHaveBeenCalledWith('a.mdl');
  expect(screen.getByRole('list', { name: 'Workspace files' })).toBeTruthy();
});

test('opens a non-active row menu without changing selection, and closes on outside click', async () => {
  const user = userEvent.setup();
  const handlers = {
    onCreate: vi.fn(),
    onImport: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    onSelect: vi.fn(),
  };
  render(
    <div>
      <button type="button">Outside</button>
      <WorkspaceFiles workspace={workspace} disabled={false} {...handlers} />
    </div>,
  );

  const trigger = screen.getByRole('button', { name: 'a.mdl actions' });
  expect(trigger.getAttribute('aria-expanded')).toBe('false');

  await user.click(trigger);
  expect(trigger.getAttribute('aria-expanded')).toBe('true');
  expect(screen.getByRole('menu', { name: 'a.mdl actions' })).toBeTruthy();
  expect(handlers.onSelect).not.toHaveBeenCalled();

  await user.click(screen.getByRole('button', { name: 'Outside' }));
  expect(screen.queryByRole('menu', { name: 'a.mdl actions' })).toBeNull();
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

  await user.click(screen.getByRole('button', { name: 'New file' }));
  await user.type(
    screen.getByPlaceholderText('file.mdl'),
    '../escape.mdl',
  );
  await user.click(screen.getByRole('button', { name: 'Add' }));
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
        name: 'a.mdl actions',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (screen.getByRole('button', { name: 'a.mdl' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

test('imports non-conflicting files immediately, without a review step', async () => {
  const onImport = vi.fn();
  render(
    <WorkspaceFiles
      workspace={workspace}
      disabled={false}
      onCreate={vi.fn()}
      onImport={onImport}
      onRename={vi.fn()}
      onDelete={vi.fn()}
      onSelect={vi.fn()}
    />,
  );

  chooseFiles([new File(['domain c {}'], 'c.mdl')]);

  await vi.waitFor(() => expect(onImport).toHaveBeenCalled());
  expect(onImport).toHaveBeenCalledWith([
    { path: 'c.mdl', content: 'domain c {}' },
  ]);
  expect(screen.queryByText('Review import')).toBeNull();
});

test('reviews a conflicting import, letting the caller exclude a file before confirming', async () => {
  const onImport = vi.fn();
  render(
    <WorkspaceFiles
      workspace={workspace}
      disabled={false}
      onCreate={vi.fn()}
      onImport={onImport}
      onRename={vi.fn()}
      onDelete={vi.fn()}
      onSelect={vi.fn()}
    />,
  );

  chooseFiles([
    new File(['domain b replaced {}'], 'b.mdl'),
    new File(['domain c {}'], 'c.mdl'),
  ]);

  await screen.findByText('Review import');
  expect(onImport).not.toHaveBeenCalled();
  expect(
    screen.getByRole('checkbox', { name: 'b.mdl' }) as HTMLInputElement,
  ).toHaveProperty('checked', true);

  fireEvent.click(screen.getByRole('checkbox', { name: 'b.mdl' }));
  fireEvent.click(screen.getByRole('button', { name: 'Import 1 file' }));

  expect(onImport).toHaveBeenCalledWith([
    { path: 'c.mdl', content: 'domain c {}' },
  ]);
  expect(screen.queryByText('Review import')).toBeNull();
});

test('cancels a reviewed import without calling onImport', async () => {
  const onImport = vi.fn();
  render(
    <WorkspaceFiles
      workspace={workspace}
      disabled={false}
      onCreate={vi.fn()}
      onImport={onImport}
      onRename={vi.fn()}
      onDelete={vi.fn()}
      onSelect={vi.fn()}
    />,
  );

  chooseFiles([new File(['domain b replaced {}'], 'b.mdl')]);

  await screen.findByText('Review import');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

  expect(onImport).not.toHaveBeenCalled();
  expect(screen.queryByText('Review import')).toBeNull();
  expect(screen.getByRole('button', { name: 'New file' })).toBeTruthy();
});
