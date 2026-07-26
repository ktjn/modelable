import type { CompileTarget } from '../client';
import type { BrowserArtifact } from '../protocol';
import type { RuntimePhase } from '../app-state';

export interface ToolbarProps {
  runtime: RuntimePhase;
  compileTarget: CompileTarget;
  actionsDisabled: boolean;
  languageCanRetry: boolean;
  persistencePhase: 'saved' | 'saving' | 'memory-only' | 'recovery-required';
  selectedArtifact: BrowserArtifact | null;
  onExportSource(): void;
  onValidate(): void;
  onFormat(): void;
  onGenerate(): void;
  onRetryCompiler(): void;
  onRetryLanguageServices(): void;
  onRetryStorage(): void;
  onCompileTargetChange(target: CompileTarget): void;
  onExportArtifact(): void;
}

export function Toolbar({
  runtime,
  compileTarget,
  actionsDisabled,
  languageCanRetry,
  persistencePhase,
  selectedArtifact,
  onExportSource,
  onValidate,
  onFormat,
  onGenerate,
  onRetryCompiler,
  onRetryLanguageServices,
  onRetryStorage,
  onCompileTargetChange,
  onExportArtifact,
}: ToolbarProps) {
  return (
    <nav className="toolbar" aria-label="Playground actions">
      <button type="button" onClick={onExportSource}>
        Export source
      </button>
      <button
        type="button"
        disabled={actionsDisabled}
        aria-keyshortcuts="Control+Shift+Enter Meta+Shift+Enter"
        onClick={onValidate}
      >
        Validate
      </button>
      <button
        type="button"
        disabled={actionsDisabled}
        aria-keyshortcuts="Shift+Alt+F"
        onClick={onFormat}
      >
        Format
      </button>
      <div className="toolbar-group">
        <select
          value={compileTarget}
          onChange={(e) =>
            onCompileTargetChange(e.target.value as CompileTarget)
          }
          disabled={actionsDisabled}
          className="compile-target-selector"
          aria-label="Target language"
        >
          <option value="jsonSchema">JSON Schema</option>
          <option value="typescript">TypeScript</option>
          <option value="sql-postgres">SQL (Postgres)</option>
          <option value="sql-clickhouse">SQL (ClickHouse)</option>
          <option value="protobuf">Protobuf</option>
          <option value="rust">Rust</option>
          <option value="java">Java</option>
          <option value="go">Go</option>
          <option value="csharp">C#</option>
          <option value="markdown">Markdown</option>
          <option value="python">Python</option>
        </select>
        <button
          type="button"
          disabled={actionsDisabled}
          aria-keyshortcuts="Control+Enter Meta+Enter"
          onClick={onGenerate}
        >
          Generate
        </button>
      </div>
      <button
        type="button"
        disabled={selectedArtifact === null}
        onClick={onExportArtifact}
      >
        Export artifact
      </button>
      {runtime === 'failed' ? (
        <button type="button" onClick={onRetryCompiler}>
          Retry compiler
        </button>
      ) : null}
      {runtime !== 'failed' && languageCanRetry ? (
        <button
          type="button"
          onClick={onRetryLanguageServices}
        >
          Retry language services
        </button>
      ) : null}
      {persistencePhase === 'memory-only' ? (
        <button
          type="button"
          onClick={onRetryStorage}
        >
          Retry storage
        </button>
      ) : null}
    </nav>
  );
}
