import { useEffect, useRef } from 'react';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';

export interface DiffViewerProps {
  original: string;
  modified: string;
}

export function DiffViewer({ original, modified }: DiffViewerProps) {
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
    });

    diffEditor.setModel({
      original: monaco.editor.createModel(original, 'modelable'),
      modified: monaco.editor.createModel(modified, 'modelable'),
    });

    return () => {
      diffEditor.dispose();
    };
  }, [original, modified]);

  return <div ref={containerRef} className="chat-message__diff-viewer" />;
}
