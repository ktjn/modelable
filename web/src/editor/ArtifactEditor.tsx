import { useEffect, useRef } from 'react';
import type { editor } from 'monaco-editor';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';

const ARTIFACT_URI = 'file:///generated.schema.json';

export interface ArtifactEditorProps {
  value: string;
}

export function ArtifactEditor({ value }: ArtifactEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const modelRef = useRef<editor.ITextModel>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }

    const model = monaco.editor.createModel(
      value,
      'json',
      monaco.Uri.parse(ARTIFACT_URI),
    );
    const artifactEditor = monaco.editor.create(container, {
      model,
      readOnly: true,
      ariaLabel: 'Generated JSON Schema',
      automaticLayout: true,
      minimap: { enabled: false },
    });
    modelRef.current = model;

    return () => {
      artifactEditor.dispose();
      model.dispose();
      modelRef.current = null;
    };
  }, []);

  useEffect(() => {
    const model = modelRef.current;
    if (model !== null && model.getValue() !== value) {
      model.setValue(value);
    }
  }, [value]);

  return <div className="artifact-editor" ref={containerRef} />;
}
