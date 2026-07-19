import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from 'react';
import type { editor } from 'monaco-editor';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';

import type { SourceEditorHandle } from './types';

const SOURCE_URI = 'file:///main.mdl';

export interface SourceEditorProps {
  initialValue: string;
  markers: editor.IMarkerData[];
  onRevisionChange(version: number): void;
}

export const SourceEditor = forwardRef<
  SourceEditorHandle,
  SourceEditorProps
>(function SourceEditor({ initialValue, markers, onRevisionChange }, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<editor.IStandaloneCodeEditor>(null);
  const modelRef = useRef<editor.ITextModel>(null);
  const versionRef = useRef(1);
  const revisionCallbackRef = useRef(onRevisionChange);

  revisionCallbackRef.current = onRevisionChange;

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }

    const model = monaco.editor.createModel(
      initialValue,
      'modelable',
      monaco.Uri.parse(SOURCE_URI),
    );
    const sourceEditor = monaco.editor.create(container, {
      model,
      ariaLabel: 'Model source',
      automaticLayout: true,
      minimap: { enabled: false },
    });
    const changeListener = model.onDidChangeContent(() => {
      versionRef.current += 1;
      revisionCallbackRef.current(versionRef.current);
    });

    modelRef.current = model;
    editorRef.current = sourceEditor;

    return () => {
      changeListener.dispose();
      sourceEditor.dispose();
      model.dispose();
      editorRef.current = null;
      modelRef.current = null;
    };
  }, [initialValue]);

  useEffect(() => {
    const model = modelRef.current;
    if (model !== null) {
      monaco.editor.setModelMarkers(model, 'modelable', markers);
    }
  }, [markers]);

  useImperativeHandle(
    ref,
    () => ({
      getSource() {
        return {
          uri: SOURCE_URI,
          text: modelRef.current?.getValue() ?? initialValue,
          version: versionRef.current,
        };
      },
      applyFormattedText(text) {
        const sourceEditor = editorRef.current;
        const model = modelRef.current;
        if (sourceEditor === null || model === null) {
          return;
        }
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
        modelRef.current?.setValue(text);
      },
      focus() {
        editorRef.current?.focus();
      },
    }),
    [initialValue],
  );

  return (
    <div
      className="source-editor"
      ref={containerRef}
      style={{ height: '100%', minHeight: '24rem' }}
    />
  );
});
