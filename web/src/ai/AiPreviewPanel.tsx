import type { BrowserDiagnostic } from '../protocol';

export interface AiPreviewState {
  kind: 'generate' | 'explain';
  source?: string;
  explanation?: string;
  diagnostics: BrowserDiagnostic[];
  providerInfo: { provider: string; model: string };
}

export interface AiPreviewPanelProps {
  preview: AiPreviewState;
  onAccept: () => void;
  onDiscard: () => void;
}

export function AiPreviewPanel({
  preview,
  onAccept,
  onDiscard,
}: AiPreviewPanelProps) {
  return (
    <section
      className="ai-preview"
      aria-label="AI preview"
      data-testid="ai-preview"
    >
      <div className="ai-preview__header">
        <h2>
          {preview.kind === 'generate'
            ? 'AI generated source'
            : 'AI explanation'}
        </h2>
        <p className="ai-preview__provider">
          {preview.providerInfo.provider} / {preview.providerInfo.model}
        </p>
      </div>
      {preview.kind === 'generate' && preview.source !== undefined ? (
        <pre className="ai-preview__source">{preview.source}</pre>
      ) : null}
      {preview.kind === 'explain' && preview.explanation !== undefined ? (
        <div className="ai-preview__explanation">{preview.explanation}</div>
      ) : null}
      {preview.diagnostics.length > 0 ? (
        <ul className="ai-preview__diagnostics">
          {preview.diagnostics.map((d, i) => (
            <li key={`${d.code}-${i}`}>
              <strong>{d.code}</strong> {d.message}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="ai-preview__actions">
        {preview.kind === 'generate' ? (
          <button type="button" onClick={onAccept}>
            Accept
          </button>
        ) : null}
        <button type="button" onClick={onDiscard}>
          {preview.kind === 'generate' ? 'Discard' : 'Close'}
        </button>
      </div>
    </section>
  );
}
