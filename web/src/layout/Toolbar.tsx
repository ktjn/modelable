import { COMPILE_TARGET_LABELS, type CompileTarget } from '../client';
import type { RuntimePhase } from '../app-state';

export const OVERLAY_SUPPORTED_TARGETS = new Set<CompileTarget>(['sql-postgres', 'sql-clickhouse']);

export interface ToolbarProps {
  runtime: RuntimePhase;
  compileTarget: CompileTarget;
  actionsDisabled: boolean;
  languageCanRetry: boolean;
  persistencePhase: 'saved' | 'saving' | 'memory-only' | 'recovery-required';
  overlayFileName: string | null;
  overlayError: string | null;
  onExportSource(): void;
  onResetToDemo(): void;
  onValidate(): void;
  onFormat(): void;
  onGenerate(): void;
  onRetryCompiler(): void;
  onRetryLanguageServices(): void;
  onRetryStorage(): void;
  onCompileTargetChange(target: CompileTarget): void;
  onOverlayFileSelected(file: File): void;
  onOverlayCleared(): void;
}

export function Toolbar({
  runtime,
  compileTarget,
  actionsDisabled,
  languageCanRetry,
  persistencePhase,
  overlayFileName,
  overlayError,
  onExportSource,
  onResetToDemo,
  onValidate,
  onFormat,
  onGenerate,
  onRetryCompiler,
  onRetryLanguageServices,
  onRetryStorage,
  onCompileTargetChange,
  onOverlayFileSelected,
  onOverlayCleared,
}: ToolbarProps) {
  const overlaySupported = OVERLAY_SUPPORTED_TARGETS.has(compileTarget);
  return (
    <nav className="toolbar" aria-label="Playground actions">
      <div className="toolbar-group">
        <button
          type="button"
          className="toolbar__secondary"
          onClick={onExportSource}
        >
          Export source
        </button>
        <button
          type="button"
          className="toolbar__secondary"
          title="Discard local changes and reload the built-in demo workspace"
          onClick={onResetToDemo}
        >
          Reload demo data
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
      </div>
      <div className="toolbar-group toolbar-group--primary">
        <select
          value={compileTarget}
          onChange={(e) =>
            onCompileTargetChange(e.target.value as CompileTarget)
          }
          disabled={actionsDisabled}
          className="compile-target-selector"
          aria-label="Target language"
        >
          {Object.entries(COMPILE_TARGET_LABELS).map(([target, label]) => (
            <option key={target} value={target}>
              {label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="toolbar__primary"
          disabled={actionsDisabled}
          aria-keyshortcuts="Control+Enter Meta+Enter"
          onClick={onGenerate}
        >
          Generate
        </button>
        {overlaySupported && (
          <div className="toolbar__overlay" title="Target overlay for this SQL target (modelable.toml [[target]] overlay file)">
            <label className="toolbar__overlay-label">
              {overlayFileName ?? 'No overlay'}
              <input
                type="file"
                accept=".toml"
                aria-label="Overlay file"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file !== undefined) {
                    onOverlayFileSelected(file);
                  }
                  event.target.value = '';
                }}
              />
            </label>
            {overlayFileName !== null && (
              <button type="button" className="toolbar__secondary" onClick={onOverlayCleared}>
                Clear overlay
              </button>
            )}
            {overlayError !== null && (
              <span role="alert" className="toolbar__overlay-error">
                {overlayError}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="toolbar-group toolbar-group--status">
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
      </div>
    </nav>
  );
}
