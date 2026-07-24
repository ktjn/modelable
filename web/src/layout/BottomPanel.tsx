import { type ReactNode, useState } from 'react';

export type BottomTab = 'diagnostics' | 'artifacts' | 'compatibility' | 'governance';

export interface BottomPanelProps {
  diagnostics: ReactNode;
  artifacts: ReactNode;
  compatibility: ReactNode;
  governance: ReactNode;
}

export function BottomPanel({
  diagnostics,
  artifacts,
  compatibility,
  governance,
}: BottomPanelProps) {
  const [tab, setTab] = useState<BottomTab>('diagnostics');

  return (
    <div className="bottom-panel" data-testid="bottom-panel">
      <div className="bottom-panel__toolbar" role="toolbar" aria-label="Bottom panel tabs">
        <button
          className={`bottom-panel__tab${tab === 'diagnostics' ? ' bottom-panel__tab--active' : ''}`}
          onClick={() => setTab('diagnostics')}
          aria-pressed={tab === 'diagnostics'}
        >
          Diagnostics
        </button>
        <button
          className={`bottom-panel__tab${tab === 'artifacts' ? ' bottom-panel__tab--active' : ''}`}
          onClick={() => setTab('artifacts')}
          aria-pressed={tab === 'artifacts'}
        >
          Generated artifacts
        </button>
        <button
          className={`bottom-panel__tab${tab === 'compatibility' ? ' bottom-panel__tab--active' : ''}`}
          onClick={() => setTab('compatibility')}
          aria-pressed={tab === 'compatibility'}
        >
          Compatibility
        </button>
        <button
          className={`bottom-panel__tab${tab === 'governance' ? ' bottom-panel__tab--active' : ''}`}
          onClick={() => setTab('governance')}
          aria-pressed={tab === 'governance'}
        >
          Governance
        </button>
      </div>
      <div className="bottom-panel__body" tabIndex={0}>
        {tab === 'diagnostics' && diagnostics}
        {tab === 'artifacts' && artifacts}
        {tab === 'compatibility' && compatibility}
        {tab === 'governance' && governance}
      </div>
    </div>
  );
}
