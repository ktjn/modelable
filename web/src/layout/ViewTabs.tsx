export type MobileView = 'files' | 'source' | 'assistant' | 'analysis';

export interface ViewTabsProps {
  mobileView: MobileView;
  onChange(view: MobileView): void;
}

export function ViewTabs({ mobileView, onChange }: ViewTabsProps) {
  return (
    <nav className="view-tabs" aria-label="View">
      <button
        type="button"
        className={`view-tab${mobileView === 'files' ? ' view-tab--active' : ''}`}
        aria-pressed={mobileView === 'files'}
        onClick={() => onChange('files')}
      >
        Files
      </button>
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
        className={`view-tab${mobileView === 'assistant' ? ' view-tab--active' : ''}`}
        aria-pressed={mobileView === 'assistant'}
        onClick={() => onChange('assistant')}
      >
        Assistant
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
