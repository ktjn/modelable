export type MobileView = 'source' | 'graph' | 'analysis';

export interface ViewTabsProps {
  mobileView: MobileView;
  onChange(view: MobileView): void;
}

export function ViewTabs({ mobileView, onChange }: ViewTabsProps) {
  return (
    <nav className="view-tabs" aria-label="View">
      <button
        type="button"
        className={`view-tab${mobileView === 'source' ? ' view-tab--active' : ''}`}
        aria-pressed={mobileView === 'source'}
        onClick={() => onChange('source')}
      >
        Source
      </button>
      <button
        type="button"
        className={`view-tab${mobileView === 'graph' ? ' view-tab--active' : ''}`}
        aria-pressed={mobileView === 'graph'}
        onClick={() => onChange('graph')}
      >
        Graph
      </button>
      <button
        type="button"
        className={`view-tab${mobileView === 'analysis' ? ' view-tab--active' : ''}`}
        aria-pressed={mobileView === 'analysis'}
        onClick={() => onChange('analysis')}
      >
        Analysis
      </button>
    </nav>
  );
}
