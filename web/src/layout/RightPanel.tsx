import type { ReactNode } from 'react';

export type RightPanelTab = 'assistant' | 'graph' | 'output';

export interface RightPanelProps {
  activeTab: RightPanelTab;
  onTabChange(tab: RightPanelTab): void;
  assistant: ReactNode;
  graph: ReactNode;
  output: ReactNode;
}

export function RightPanel({
  activeTab,
  onTabChange,
  assistant,
  graph,
  output,
}: RightPanelProps) {
  return (
    <div className="right-panel" data-active-tab={activeTab}>
      <div className="right-panel__tabs" role="tablist" aria-label="Right panel">
        <TabButton
          id="assistant"
          label="Assistant"
          active={activeTab === 'assistant'}
          onClick={() => onTabChange('assistant')}
        />
        <TabButton
          id="graph"
          label="Graph"
          active={activeTab === 'graph'}
          onClick={() => onTabChange('graph')}
        />
        <TabButton
          id="output"
          label="Output"
          active={activeTab === 'output'}
          onClick={() => onTabChange('output')}
        />
      </div>
      <div id="right-panel-body" className="right-panel__body" role="tabpanel">
        {activeTab === 'assistant' && assistant}
        {activeTab === 'graph' && graph}
        {activeTab === 'output' && output}
      </div>
    </div>
  );
}

function TabButton({
  id,
  label,
  active,
  onClick,
}: {
  id: string;
  label: string;
  active: boolean;
  onClick(): void;
}) {
  return (
    <button
      type="button"
      role="tab"
      id={`right-panel-tab-${id}`}
      aria-selected={active}
      aria-controls="right-panel-body"
      className={`right-panel__tab${active ? ' right-panel__tab--active' : ''}`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}
