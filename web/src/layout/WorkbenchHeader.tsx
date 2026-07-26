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
      <div>
        <p className="eyebrow">Local schema workbench</p>
        <h1>Modelable playground</h1>
      </div>
      <div className="state-block">
        <span className="state-signal" aria-hidden="true" />
        <p
          className="status"
          role={statusIsError ? 'alert' : 'status'}
          aria-live={statusIsError ? 'assertive' : 'polite'}
        >
          {status} · {diagnosticLabel}
        </p>
        <p className="persistence-status" aria-live="polite">
          {persistencePhase === 'saved'
            ? 'Saved locally'
            : persistencePhase === 'saving'
              ? 'Saving locally…'
              : 'Storage unavailable · changes remain in this tab'}
        </p>
        <p className="persistence-status" aria-live="polite">
          {languageStatus}
        </p>
      </div>
    </header>
  );
}
