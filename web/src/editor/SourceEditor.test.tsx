// @vitest-environment jsdom

import { render } from '@testing-library/react';
import type { editor } from 'monaco-editor';
import { beforeEach, expect, test, vi } from 'vitest';

import type { PlaygroundFile } from '../workspace';
import type { BrowserLanguageServiceController } from '../language/BrowserLanguageServiceController';
import { SourceEditor } from './SourceEditor';

const monaco = vi.hoisted(() => {
  const models = new Map<string, editor.ITextModel>();
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
    createModel: vi.fn(
      (content: string, _language: string, uri: string) => {
        const model = fakeModel(content, uri);
        models.set(uri, model);
        return model;
      },
    ),
    models,
    setModelMarkers: vi.fn(),
    sourceEditor,
    registerCompletionItemProvider: vi.fn(() => ({ dispose: vi.fn() })),
    registerHoverProvider: vi.fn(() => ({ dispose: vi.fn() })),
    registerDefinitionProvider: vi.fn(() => ({ dispose: vi.fn() })),
    registerReferenceProvider: vi.fn(() => ({ dispose: vi.fn() })),
    registerRenameProvider: vi.fn(() => ({ dispose: vi.fn() })),
    registerLanguage: vi.fn(() => ({ dispose: vi.fn() })),
  };
});

vi.mock('monaco-editor/esm/vs/editor/editor.api.js', () => ({
  Range: class {
    constructor(
      readonly startLineNumber: number,
      readonly startColumn: number,
      readonly endLineNumber: number,
      readonly endColumn: number,
    ) {}
  },
  Uri: {
    parse: (uri: string) => uri,
  },
  languages: {
    register: monaco.registerLanguage,
    CompletionItemKind: {
      Keyword: 1,
      Snippet: 2,
      Module: 3,
      Class: 4,
      Property: 5,
      Reference: 6,
      Value: 7,
      Text: 8,
    },
    registerCompletionItemProvider: monaco.registerCompletionItemProvider,
    registerHoverProvider: monaco.registerHoverProvider,
    registerDefinitionProvider: monaco.registerDefinitionProvider,
    registerReferenceProvider: monaco.registerReferenceProvider,
    registerRenameProvider: monaco.registerRenameProvider,
  },
  editor: {
    create: monaco.create,
    createModel: monaco.createModel,
    setModelMarkers: monaco.setModelMarkers,
  },
}));

vi.mock(
  'monaco-editor/esm/vs/editor/contrib/hover/browser/hoverContribution.js',
  () => ({}),
);
vi.mock(
  'monaco-editor/esm/vs/editor/contrib/suggest/browser/suggestController.js',
  () => ({}),
);

beforeEach(() => {
  vi.clearAllMocks();
  monaco.models.clear();
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

test('does not overwrite newer Monaco edits with an older React snapshot', () => {
  const onContentChange = vi.fn();
  const initialFile: PlaygroundFile = {
    path: 'main.mdl',
    content: '',
    version: 1,
  };
  const props = {
    activeFile: 'main.mdl',
    markersByUri: new Map(),
    onContentChange,
  };
  const { rerender } = render(
    <SourceEditor {...props} files={[initialFile]} />,
  );
  const model = monaco.models.get('file:///main.mdl');
  expect(model).toBeDefined();

  model?.setValue('d');
  model?.setValue('do');
  expect(onContentChange).toHaveBeenNthCalledWith(1, 'main.mdl', 'd');
  expect(onContentChange).toHaveBeenNthCalledWith(2, 'main.mdl', 'do');

  rerender(
    <SourceEditor
      {...props}
      files={[{ ...initialFile, content: 'd', version: 2 }]}
    />,
  );

  expect(model?.getValue()).toBe('do');
});

test('registers language providers once and disposes them with the editor', () => {
  const completionDisposable = { dispose: vi.fn() };
  const hoverDisposable = { dispose: vi.fn() };
  monaco.registerCompletionItemProvider.mockReturnValueOnce(
    completionDisposable,
  );
  monaco.registerHoverProvider.mockReturnValueOnce(hoverDisposable);
  const workspace = {
    schemaVersion: 1 as const,
    id: 'local',
    revision: 1,
    activeFile: 'main.mdl',
    files: [
      {
        path: 'main.mdl',
        content: 'domain demo {}',
        version: 1,
      },
    ],
  };
  const { unmount } = render(
    <SourceEditor
      files={workspace.files}
      activeFile={workspace.activeFile}
      markersByUri={new Map()}
      languageController={
        {
          completion: vi.fn(),
          hover: vi.fn(),
        } as unknown as BrowserLanguageServiceController
      }
      getWorkspace={() => workspace}
      onContentChange={vi.fn()}
    />,
  );

  expect(monaco.registerCompletionItemProvider).toHaveBeenCalledTimes(1);
  expect(monaco.registerHoverProvider).toHaveBeenCalledTimes(1);
  unmount();
  expect(completionDisposable.dispose).toHaveBeenCalledTimes(1);
  expect(hoverDisposable.dispose).toHaveBeenCalledTimes(1);
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
