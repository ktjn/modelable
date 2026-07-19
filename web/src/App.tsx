import initialSource from './example.mdl?raw';

export function App() {
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
        <section
          id="source-editor"
          aria-label="Modelable source"
          data-initial-source={initialSource}
          tabIndex={-1}
        />
        <section aria-label="Generated JSON Schema" />
      </section>
    </main>
  );
}
