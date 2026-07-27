export interface WorkbenchHeaderProps {
  status: string;
  diagnosticLabel: string;
  statusIsError: boolean;
  persistencePhase: 'saved' | 'saving' | 'memory-only' | 'recovery-required';
  languageStatus: string;
}

export function WorkbenchHeader({
  status,
  diagnosticLabel,
  statusIsError,
  persistencePhase,
  languageStatus,
}: WorkbenchHeaderProps) {
  return (
    <header className="workbench-header">
      <div className="workbench-header__brand">
        <h1 className="workbench-header__logo">Modelable</h1>
        <span className="workbench-header__tagline">Playground</span>
      </div>
      <div className="workbench-header__badges">
        <span
          className={`badge${statusIsError ? ' badge--error' : ' badge--ok'}`}
          role={statusIsError ? 'alert' : 'status'}
          aria-live={statusIsError ? 'assertive' : 'polite'}
        >
          {status}
          <span className="badge__separator">·</span>
          {diagnosticLabel}
        </span>
        <span className="badge" aria-live="polite">
          {persistencePhase === 'saved'
            ? 'Saved locally'
            : persistencePhase === 'saving'
              ? 'Saving…'
              : 'Memory-only'}
        </span>
        <span className="badge badge--muted" aria-live="polite">
          {languageStatus}
        </span>
      </div>
    </header>
  );
}
