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
        <TabButton
          label="Problems"
          count={diagnosticsCount}
          active={tab === 'diagnostics'}
          onClick={() => setTab('diagnostics')}
        />
        <TabButton
          label="Compatibility"
          count={compatibilityCount}
          active={tab === 'compatibility'}
          onClick={() => setTab('compatibility')}
        />
        <TabButton
          label="Governance"
          count={governanceCount}
          active={tab === 'governance'}
          onClick={() => setTab('governance')}
        />
      </div>
      <div className="bottom-panel__body" tabIndex={0}>
        {tab === 'diagnostics' && diagnostics}
        {tab === 'compatibility' && compatibility}
        {tab === 'governance' && governance}
      </div>
    </div>
  );
}

function TabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick(): void;
}) {
  return (
    <button
      className={`tab${active ? ' tab--active' : ''}`}
      onClick={onClick}
      aria-selected={active}
      role="tab"
    >
      {label}
      <TabCount count={count} />
    </button>
  );
}

function TabCount({ count }: { count?: number }) {
  if (count === undefined || count === 0) {
    return null;
  }
  return <span className="tab__count">{count}</span>;
}
