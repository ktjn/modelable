import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from 'react';
import type { editor } from 'monaco-editor';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';
import 'monaco-editor/esm/vs/editor/contrib/hover/browser/hoverContribution.js';
import 'monaco-editor/esm/vs/editor/contrib/suggest/browser/suggestController.js';

import type { PlaygroundFile } from '../workspace';
import type { BrowserLanguageServiceController } from '../language/BrowserLanguageServiceController';
import { registerModelableProviders } from '../language/monaco-providers';
import type { PlaygroundWorkspace } from '../workspace';
import {
  createSourceModelRegistry,
  type SourceModelRegistry,
} from './SourceModelRegistry';
import type { SourceEditorHandle } from './types';

export interface SourceEditorProps {
  files: PlaygroundFile[];
  activeFile: string;
  markersByUri: ReadonlyMap<string, editor.IMarkerData[]>;
  languageController?: BrowserLanguageServiceController;
  getWorkspace?: () => PlaygroundWorkspace;
  onContentChange(path: string, content: string): void;
}

interface LegacySourceEditorProps {
  initialValue: string;
  markers: editor.IMarkerData[];
  onRevisionChange(version: number): void;
}

const LEGACY_SOURCE_PATH = 'main.mdl';

export const SourceEditor = forwardRef<
  SourceEditorHandle,
  SourceEditorProps | LegacySourceEditorProps
>(function SourceEditor(props, ref) {
  const legacy = 'initialValue' in props;
  const files: PlaygroundFile[] = legacy
    ? [
        {
          path: LEGACY_SOURCE_PATH,
          content: props.initialValue,
          version: 1,
        },
      ]
    : props.files;
  const activeFile = legacy ? LEGACY_SOURCE_PATH : props.activeFile;
  const markersByUri: ReadonlyMap<string, editor.IMarkerData[]> = legacy
    ? new Map([[sourceUri(LEGACY_SOURCE_PATH), props.markers]])
    : props.markersByUri;
  const languageController = legacy
    ? undefined
    : props.languageController;
  const getWorkspace = legacy ? undefined : props.getWorkspace;

  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<editor.IStandaloneCodeEditor>(null);
  const registryRef = useRef<SourceModelRegistry>(null);
  const listenersRef = useRef(
    new Map<string, { dispose(): void }>(),
  );
  const localVersionHighWaterRef = useRef(new Map<string, number>());
  const viewStatesRef = useRef(
    new Map<string, editor.ICodeEditorViewState | null>(),
  );
  const activePathRef = useRef(activeFile);
  const filesRef = useRef(files);
  const legacyVersionRef = useRef(1);
  const contentCallbackRef = useRef<
    (path: string, content: string) => void
  >(() => undefined);

  filesRef.current = files;
  contentCallbackRef.current = legacy
    ? () => {
        legacyVersionRef.current += 1;
        props.onRevisionChange(legacyVersionRef.current);
      }
    : props.onContentChange;

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }

    const registry = createSourceModelRegistry({
      createModel(content, uri) {
        return monaco.editor.createModel(
          content,
          'modelable',
          monaco.Uri.parse(uri),
        );
      },
    });
    const sourceEditor = monaco.editor.create(container, {
      model: null,
      ariaLabel: 'Model source',
      automaticLayout: true,
      minimap: { enabled: false },
    });
    registryRef.current = registry;
    editorRef.current = sourceEditor;

    return () => {
      for (const listener of listenersRef.current.values()) {
        listener.dispose();
      }
      listenersRef.current.clear();
      sourceEditor.dispose();
      registry.dispose();
      editorRef.current = null;
      registryRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (
      languageController === undefined ||
      getWorkspace === undefined
    ) {
      return;
    }
    return registerModelableProviders(
      monaco,
      languageController,
      getWorkspace,
    ).dispose;
  }, [getWorkspace, languageController]);

  useEffect(() => {
    const registry = registryRef.current;
    const sourceEditor = editorRef.current;
    if (registry === null || sourceEditor === null) {
      return;
    }

    const reconciledFiles = files.map((file) => {
      const localVersion = localVersionHighWaterRef.current.get(file.path);
      if (localVersion === undefined) {
        return file;
      }
      if (file.version >= localVersion) {
        localVersionHighWaterRef.current.delete(file.path);
        return file;
      }
      const model = registry.model(file.path);
      return model === undefined
        ? file
        : { ...file, content: model.getValue() };
    });
    registry.reconcile(reconciledFiles);
    const paths = new Set(registry.paths());
    for (const path of localVersionHighWaterRef.current.keys()) {
      if (!paths.has(path)) {
        localVersionHighWaterRef.current.delete(path);
      }
    }
    for (const [path, listener] of listenersRef.current) {
      if (!paths.has(path)) {
        listener.dispose();
        listenersRef.current.delete(path);
      }
    }
    for (const path of paths) {
      if (listenersRef.current.has(path)) {
        continue;
      }
      const model = registry.model(path);
      if (model === undefined) {
        continue;
      }
      listenersRef.current.set(
        path,
        model.onDidChangeContent(() => {
          if (!registry.isApplyingExternalChange()) {
            const renderedVersion =
              filesRef.current.find((file) => file.path === path)?.version ??
              0;
            const localVersion =
              localVersionHighWaterRef.current.get(path) ?? renderedVersion;
            localVersionHighWaterRef.current.set(
              path,
              Math.max(localVersion, renderedVersion) + 1,
            );
            contentCallbackRef.current(path, model.getValue());
          }
        }),
      );
    }

    switchModel(sourceEditor, registry, activeFile, viewStatesRef.current);
    activePathRef.current = activeFile;
  }, [activeFile, files]);

  useEffect(() => {
    const registry = registryRef.current;
    if (registry === null) {
      return;
    }
    for (const path of registry.paths()) {
      const model = registry.model(path);
      if (model !== undefined) {
        monaco.editor.setModelMarkers(
          model,
          'modelable',
          markersByUri.get(sourceUri(path)) ?? [],
        );
      }
    }
  }, [files, markersByUri]);

  useImperativeHandle(
    ref,
    () => ({
      getSource() {
        const path = activePathRef.current;
        const file = filesRef.current.find(
          (candidate) => candidate.path === path,
        );
        return {
          uri: sourceUri(path),
          text: registryRef.current?.model(path)?.getValue() ?? '',
          version: legacy ? legacyVersionRef.current : (file?.version ?? 1),
        };
      },
      applyFormattedText(pathOrText: string, formattedText?: string) {
        const path =
          formattedText === undefined ? activePathRef.current : pathOrText;
        const text = formattedText ?? pathOrText;
        const sourceEditor = editorRef.current;
        const registry = registryRef.current;
        const model = registry?.model(path);
        if (
          sourceEditor === null ||
          registry === null ||
          model === undefined
        ) {
          return;
        }
        switchModel(
          sourceEditor,
          registry,
          path,
          viewStatesRef.current,
        );
        activePathRef.current = path;
        sourceEditor.pushUndoStop();
        sourceEditor.executeEdits('modelable.format', [
          {
            range: model.getFullModelRange(),
            text,
            forceMoveMarkers: true,
          },
        ]);
        sourceEditor.pushUndoStop();
      },
      replaceText(text) {
        registryRef.current?.model(activePathRef.current)?.setValue(text);
      },
      focus() {
        editorRef.current?.focus();
      },
    }),
    [legacy],
  );

  return <div className="source-editor" ref={containerRef} />;
});

function switchModel(
  sourceEditor: editor.IStandaloneCodeEditor,
  registry: SourceModelRegistry,
  path: string,
  viewStates: Map<string, editor.ICodeEditorViewState | null>,
): void {
  const model = registry.model(path);
  if (model === undefined || sourceEditor.getModel() === model) {
    return;
  }
  const previousModel = sourceEditor.getModel();
  if (previousModel !== null) {
    const previousPath = registry
      .paths()
      .find((candidate) => registry.model(candidate) === previousModel);
    if (previousPath !== undefined) {
      viewStates.set(previousPath, sourceEditor.saveViewState());
    }
  }
  sourceEditor.setModel(model);
  const viewState = viewStates.get(path);
  if (viewState !== undefined && viewState !== null) {
    sourceEditor.restoreViewState(viewState);
  }
}

function sourceUri(path: string): string {
  return `file:///${path.split('/').map(encodeURIComponent).join('/')}`;
}
