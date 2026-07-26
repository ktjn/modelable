export interface MetricsFooterProps {
  initializationDuration: number | null;
  lastOperationDuration: number | null;
}

export function MetricsFooter({
  initializationDuration,
  lastOperationDuration,
}: MetricsFooterProps) {
  return (
    <footer
      className="metrics-strip"
      data-testid="metrics"
      data-initialization-duration-ms={initializationDuration ?? undefined}
    >
      <p className="metrics-label">Browser compiler timing</p>
      <p className="timings">
        Initialization{' '}
        {initializationDuration === null
          ? 'pending'
          : `${initializationDuration.toFixed(1)} ms`}
        {' · '}Operation{' '}
        {lastOperationDuration === null
          ? 'not run'
          : `${lastOperationDuration.toFixed(1)} ms`}
      </p>
      <p className="privacy-note">No source leaves this page</p>
    </footer>
  );
}
