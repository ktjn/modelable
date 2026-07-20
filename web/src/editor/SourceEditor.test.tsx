// @vitest-environment jsdom

import { render } from '@testing-library/react';
import type { editor } from 'monaco-editor';
import { beforeEach, expect, test, vi } from 'vitest';

import type { PlaygroundFile } from '../workspace';
import { SourceEditor } from './SourceEditor';

const monaco = vi.hoisted(() => {
  const sourceEditor = {
    currentModel: null as editor.ITextModel | null,
    dispose: vi.fn(),
    executeEdits: vi.fn(),
    focus: vi.fn(),
    getModel: vi.fn(() => sourceEditor.currentModel),
    pushUndoStop: vi.fn(),
    restoreViewState: vi.fn(),
    saveViewState: vi.fn<() => editor.ICodeEditorViewState | null>(
      () => null,
    ),
    setModel: vi.fn((model: editor.ITextModel | null) => {
      sourceEditor.currentModel = model;
    }),
  };

  return {
    create: vi.fn(
      (
        _container: HTMLElement,
        options: { model: editor.ITextModel | null },
      ) => {
        sourceEditor.currentModel = options.model;
        return sourceEditor;
      },
    ),
    createModel: vi.fn((content: string, _language: string, uri: string) =>
      fakeModel(content, uri),
    ),
    setModelMarkers: vi.fn(),
    sourceEditor,
  };
});

vi.mock('monaco-editor/esm/vs/editor/editor.api.js', () => ({
  Uri: {
    parse: (uri: string) => uri,
  },
  editor: {
    create: monaco.create,
    createModel: monaco.createModel,
    setModelMarkers: monaco.setModelMarkers,
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  monaco.sourceEditor.currentModel = null;
});

test('switches active models and restores in-session view state', () => {
  const aViewState = {
    cursorState: [],
    viewState: {},
    contributionsState: {},
  } as unknown as editor.ICodeEditorViewState;
  const bViewState = {
    cursorState: [],
    viewState: {},
    contributionsState: {},
  } as unknown as editor.ICodeEditorViewState;
  monaco.sourceEditor.saveViewState
    .mockReturnValueOnce(aViewState)
    .mockReturnValueOnce(bViewState);

  const files: PlaygroundFile[] = [
    { path: 'a.mdl', content: 'domain a {}', version: 1 },
    { path: 'b.mdl', content: 'domain b {}', version: 1 },
  ];
  const props = {
    files,
    markersByUri: new Map(),
    onContentChange: vi.fn(),
  };
  const { rerender } = render(
    <SourceEditor {...props} activeFile="a.mdl" />,
  );

  rerender(<SourceEditor {...props} activeFile="b.mdl" />);
  rerender(<SourceEditor {...props} activeFile="a.mdl" />);

  expect(monaco.sourceEditor.restoreViewState).toHaveBeenCalledWith(
    aViewState,
  );
});

function fakeModel(content: string, uri: string): editor.ITextModel {
  let value = content;
  const listeners = new Set<() => void>();
  return {
    uri: { toString: () => uri },
    dispose: vi.fn(),
    getFullModelRange: vi.fn(() => ({})),
    getValue: vi.fn(() => value),
    onDidChangeContent: vi.fn((listener: () => void) => {
      listeners.add(listener);
      return {
        dispose() {
          listeners.delete(listener);
        },
      };
    }),
    setValue: vi.fn((next: string) => {
      value = next;
      for (const listener of listeners) {
        listener();
      }
    }),
  } as unknown as editor.ITextModel;
}
