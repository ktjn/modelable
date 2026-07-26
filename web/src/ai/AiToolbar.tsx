import { providerStatusLabel, type ProviderState } from './provider-state';

export interface AiToolbarProps {
  aiState: ProviderState;
  aiPending: boolean;
  actionsDisabled: boolean;
  onDownload(): void;
  onFallback(): void;
  onGenerateEntity(): void;
  onExplain(): void;
  onSuggestProjection(): void;
}

export function AiToolbar({
  aiState,
  aiPending,
  actionsDisabled,
  onDownload,
  onFallback,
  onGenerateEntity,
  onExplain,
  onSuggestProjection,
}: AiToolbarProps) {
  return (
    <section className="ai-toolbar" aria-label="AI model status">
      <p className="ai-status">{providerStatusLabel(aiState)}</p>
      {aiState.status === 'downloading' ? (
        <div className="ai-progress">
          <div
            className="ai-progress__bar"
            role="progressbar"
            aria-valuenow={Math.round(aiState.progress * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            style={{ width: `${(aiState.progress * 100).toFixed(1)}%` }}
          />
        </div>
      ) : null}
      {aiState.status === 'idle' ? (
        <button type="button" onClick={onDownload}>
          Download AI model
        </button>
      ) : null}
      {aiState.status === 'unsupported' || aiState.status === 'error' ? (
        <button type="button" onClick={onFallback}>
          Use heuristic AI
        </button>
      ) : null}
      {aiState.status === 'ready' ? (
        <>
          <button
            type="button"
            disabled={actionsDisabled || aiPending}
            onClick={onGenerateEntity}
          >
            Generate entity
          </button>
          <button
            type="button"
            disabled={actionsDisabled || aiPending}
            onClick={onExplain}
          >
            Explain
          </button>
          <button
            type="button"
            disabled={actionsDisabled || aiPending}
            onClick={onSuggestProjection}
          >
            Suggest projection
          </button>
        </>
      ) : null}
    </section>
  );
}
