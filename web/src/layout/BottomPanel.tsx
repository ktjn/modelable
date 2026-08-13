import { type ReactNode, useState } from 'react';

export type BottomTab = 'diagnostics' | 'compatibility' | 'governance';

export interface BottomPanelProps {
  diagnostics: ReactNode;
  compatibility: ReactNode;
  governance: ReactNode;
  diagnosticsCount?: number;
  compatibilityCount?: number;
  governanceCount?: number;
}

export function BottomPanel({
  diagnostics,
  compatibility,
  governance,
  diagnosticsCount,
  compatibilityCount,
  governanceCount,
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
          <TabCount count={diagnosticsCount} />
        </button>
        <button
          className={`tab${tab === 'compatibility' ? ' tab--active' : ''}`}
          onClick={() => setTab('compatibility')}
          aria-selected={tab === 'compatibility'}
          role="tab"
        >
          Compatibility
          <TabCount count={compatibilityCount} />
        </button>
        <button
          className={`tab${tab === 'governance' ? ' tab--active' : ''}`}
          onClick={() => setTab('governance')}
          aria-selected={tab === 'governance'}
          role="tab"
        >
          Governance
          <TabCount count={governanceCount} />
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

function TabCount({ count }: { count?: number }) {
  if (count === undefined || count === 0) {
    return null;
  }
  return <span className="tab__count">{count}</span>;
}
