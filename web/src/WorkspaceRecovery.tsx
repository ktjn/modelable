export interface WorkspaceRecoveryProps {
  reason: 'invalid' | 'incompatible';
  onExport(): void;
  onReset(): void;
  onRetry(): void;
}

export function WorkspaceRecovery({
  reason,
  onExport,
  onReset,
  onRetry,
}: WorkspaceRecoveryProps) {
  return (
    <section className="workspace-recovery" aria-labelledby="recovery-title">
      <p className="eyebrow">Local workspace recovery</p>
      <h2 id="recovery-title">Stored workspace needs recovery</h2>
      <p>
        {reason === 'incompatible'
          ? 'This workspace was saved by an unsupported schema version.'
          : 'The saved workspace is invalid and was left unchanged.'}
      </p>
      <div className="workspace-recovery-actions">
        <button type="button" onClick={onExport}>
          Export recovery data
        </button>
        <button type="button" onClick={onReset}>
          Reset local workspace
        </button>
        <button type="button" onClick={onRetry}>
          Retry storage
        </button>
      </div>
    </section>
  );
}
