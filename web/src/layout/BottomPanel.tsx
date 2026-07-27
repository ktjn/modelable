import { type ReactNode, useState } from 'react';

export type BottomTab = 'diagnostics' | 'compatibility' | 'governance';

export interface BottomPanelProps {
  diagnostics: ReactNode;
  compatibility: ReactNode;
  governance: ReactNode;
}

export function BottomPanel({
  diagnostics,
  compatibility,
  governance,
}: BottomPanelProps) {
  const [tab, setTab] = useState<BottomTab>('diagnostics');

  return (
    <div className="bottom-panel" data-testid="bottom-panel">
      <div className="tab-strip" role="tablist" aria-label="Bottom panel tabs">
        <button
          className={`tab${tab === 'diagnostics' ? ' tab--active' : ''}`}
          onClick={() => setTab('diagnostics')}
          aria-selected={tab === 'diagnostics'}
          role="tab"
        >
          Problems
        </button>
        <button
          className={`tab${tab === 'compatibility' ? ' tab--active' : ''}`}
          onClick={() => setTab('compatibility')}
          aria-selected={tab === 'compatibility'}
          role="tab"
        >
          Compatibility
        </button>
        <button
          className={`tab${tab === 'governance' ? ' tab--active' : ''}`}
          onClick={() => setTab('governance')}
          aria-selected={tab === 'governance'}
          role="tab"
        >
          Governance
        </button>
      </div>
      <div className="bottom-panel__body" tabIndex={0}>
        {tab === 'diagnostics' && diagnostics}
        {tab === 'compatibility' && compatibility}
        {tab === 'governance' && governance}
      </div>
    </div>
  );
}
