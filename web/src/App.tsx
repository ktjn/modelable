import { useRef } from 'react';

import initialSource from './example.mdl?raw';
import { ArtifactEditor } from './editor/ArtifactEditor';
import { SourceEditor } from './editor/SourceEditor';
import type { SourceEditorHandle } from './editor/types';

export function App() {
  const sourceEditorRef = useRef<SourceEditorHandle>(null);

  return (
    <main className="workbench">
      <header className="workbench-header">
        <div>
          <p className="eyebrow">Local schema workbench</p>
          <h1>Modelable playground</h1>
        </div>
        <p role="status" aria-live="polite">
          Initializing compiler…
        </p>
      </header>
      <nav className="toolbar" aria-label="Playground actions">
        <button type="button">Import</button>
        <button type="button">Export source</button>
        <button type="button" disabled>Validate</button>
        <button type="button" disabled>Format</button>
        <button type="button" disabled>Generate</button>
        <button type="button" disabled>Export artifact</button>
      </nav>
      <section className="workspace" aria-label="Single-file workspace">
        <section id="source-editor" aria-label="Modelable source" tabIndex={-1}>
          <SourceEditor
            ref={sourceEditorRef}
            initialValue={initialSource}
            markers={[]}
            onRevisionChange={() => undefined}
          />
        </section>
        <section aria-label="Generated JSON Schema">
          <ArtifactEditor value="" />
        </section>
      </section>
    </main>
  );
}
