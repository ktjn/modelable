import { describe, expect, test } from 'vitest';

import {
  WorkspaceValidationError,
  createDefaultWorkspace,
  mutateWorkspace,
  mutateWorkspaceBatch,
  normalizeWorkspacePath,
  parseWorkspaceRecord,
  workspaceSources,
} from './workspace';

describe('playground workspace paths', () => {
  test.each([
    ['', ''],
    ['../secret.mdl', '../secret.mdl'],
    ['/absolute.mdl', '/absolute.mdl'],
    ['file:///main.mdl', 'file:///main.mdl'],
    ['domain//model.mdl', 'domain//model.mdl'],
    ['domain/./model.mdl', 'domain/./model.mdl'],
    ['domain/model.txt', 'domain/model.txt'],
    ['domain/\u202emodel.mdl', 'domain/\u202emodel.mdl'],
  ])('rejects unsafe path %s', (input) => {
    expect(() => normalizeWorkspacePath(input)).toThrow(
      WorkspaceValidationError,
    );
  });

  test('normalizes separators and creates the default workspace', () => {
    expect(normalizeWorkspacePath('domain\\model.mdl')).toBe(
      'domain/model.mdl',
    );
    expect(createDefaultWorkspace('domain demo {}')).toEqual({
      schemaVersion: 1,
      id: 'local',
      revision: 1,
      files: [
        {
          path: 'main.mdl',
          content: 'domain demo {}',
          version: 1,
        },
      ],
      activeFile: 'main.mdl',
    });
  });
});

test('mutations are immutable and increment exact versions', () => {
  const initial = createDefaultWorkspace('domain demo {}');
  const created = mutateWorkspace(initial, {
    type: 'create',
    path: 'customer/customer.mdl',
    content: 'domain customer {}',
  });
  const edited = mutateWorkspace(created, {
    type: 'update',
    path: 'customer/customer.mdl',
    content: 'domain customer { entity Customer@1 {} }',
  });
  const renamed = mutateWorkspace(edited, {
    type: 'rename',
    from: 'customer/customer.mdl',
    to: 'customer/model.mdl',
  });

  expect(initial.files).toHaveLength(1);
  expect(created.revision).toBe(2);
  expect(edited.revision).toBe(3);
  expect(
    edited.files.find((file) => file.path === 'customer/customer.mdl'),
  ).toMatchObject({ version: 2 });
  expect(renamed).toMatchObject({
    revision: 4,
    activeFile: 'customer/model.mdl',
  });
});

test('rejects duplicates, missing selections, and final-file deletion', () => {
  const workspace = createDefaultWorkspace('domain demo {}');
  expect(() =>
    mutateWorkspace(workspace, { type: 'create', path: 'main.mdl' }),
  ).toThrow(WorkspaceValidationError);
  expect(() =>
    mutateWorkspace(workspace, { type: 'select', path: 'missing.mdl' }),
  ).toThrow(WorkspaceValidationError);
  expect(() =>
    mutateWorkspace(workspace, { type: 'delete', path: 'main.mdl' }),
  ).toThrow(WorkspaceValidationError);
});

test('parses only complete valid records and emits sorted browser sources', () => {
  const parsed = parseWorkspaceRecord({
    schemaVersion: 1,
    id: 'local',
    revision: 7,
    activeFile: 'z.mdl',
    files: [
      { path: 'z.mdl', content: 'domain z {}', version: 3 },
      { path: 'a.mdl', content: 'domain a {}', version: 2 },
    ],
  });

  expect(workspaceSources(parsed)).toEqual([
    { uri: 'file:///a.mdl', text: 'domain a {}', version: 2 },
    { uri: 'file:///z.mdl', text: 'domain z {}', version: 3 },
  ]);
  try {
    parseWorkspaceRecord({ ...parsed, schemaVersion: 2 });
    expect.unreachable('schema version 2 must be rejected');
  } catch (error) {
    expect(error).toMatchObject({
      name: 'WorkspaceValidationError',
      reason: 'incompatible',
    });
  }
});

test('distinguishes malformed records from incompatible schema versions', () => {
  const record = {
    schemaVersion: 1,
    id: 'local',
    revision: 1,
    files: [{ path: 'main.mdl', content: '', version: 1 }],
    activeFile: 'main.mdl',
  };

  for (const malformed of [
    {
      id: record.id,
      revision: record.revision,
      files: record.files,
      activeFile: record.activeFile,
    },
    { ...record, unexpected: true },
    {
      ...record,
      files: [
        { path: 'folder/model.mdl', content: '', version: 1 },
        { path: 'folder\\model.mdl', content: '', version: 1 },
      ],
      activeFile: 'folder/model.mdl',
    },
  ]) {
    try {
      parseWorkspaceRecord(malformed);
      expect.unreachable('malformed record must be rejected');
    } catch (error) {
      expect(error).toMatchObject({
        name: 'WorkspaceValidationError',
        reason: 'invalid',
      });
    }
  }
});

test('a failed batch leaves the original workspace unchanged', () => {
  const initial = createDefaultWorkspace('domain demo {}');
  expect(() =>
    mutateWorkspaceBatch(initial, [
      {
        type: 'create',
        path: 'customer.mdl',
        content: 'domain customer {}',
      },
      { type: 'create', path: '../escape.mdl', content: 'secret' },
    ]),
  ).toThrow(WorkspaceValidationError);
  expect(initial).toEqual(createDefaultWorkspace('domain demo {}'));
});
