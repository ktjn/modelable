import { useEffect, useRef } from 'react';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';

export interface ArtifactDiffViewerProps {
  original: string;
  modified: string;
}

export function ArtifactDiffViewer({
  original,
  modified,
}: ArtifactDiffViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) return undefined;

    const diffEditor = monaco.editor.createDiffEditor(container, {
      readOnly: true,
      renderSideBySide: true,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      renderOverviewRuler: false,
      folding: true,
      lineNumbers: 'on',
      automaticLayout: true,
    });

    const originalModel = monaco.editor.createModel(original, 'json');
    const modifiedModel = monaco.editor.createModel(modified, 'json');
    diffEditor.setModel({ original: originalModel, modified: modifiedModel });

    return () => {
      diffEditor.dispose();
      originalModel.dispose();
      modifiedModel.dispose();
    };
  }, [original, modified]);

  return <div className="artifact-diff-viewer" ref={containerRef} />;
}
