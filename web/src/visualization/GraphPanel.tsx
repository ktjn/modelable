import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import type { BrowserGraphResult, BrowserGraphMode } from '../protocol';
import type { GraphNode } from './graph-types';
import { useGraphExport } from './useGraphExport';
import { useGraphLayout } from './useGraphLayout';
import { useGraphSync } from './useGraphSync';
import { edgeTypes, nodeTypes } from './registry';

export interface GraphPanelProps {
  graphResult: BrowserGraphResult | null;
  mode: BrowserGraphMode;
  onModeChange: (mode: BrowserGraphMode) => void;
  cursorUri?: string | null;
  cursorLine?: number | null;
  onRevealRange?: (uri: string, line: number, character: number) => void;
}

function GraphPanelInner({
  graphResult,
  mode,
  onModeChange,
  cursorUri = null,
  cursorLine = null,
  onRevealRange,
}: GraphPanelProps) {
  const { containerRef, exportSvg, exportPng } = useGraphExport();
  const { nodes, edges, loading } = useGraphLayout(graphResult);
  const { selectedNodeId, onNodeClick } = useGraphSync(
    nodes,
    cursorUri ?? null,
    cursorLine ?? null,
    onRevealRange,
  );

  const nodesWithSelection = selectedNodeId
    ? nodes.map((node) => ({
        ...node,
        selected: node.id === selectedNodeId,
      }))
    : nodes;

  return (
    <div className="graph-panel" role="region" aria-label="Model graph">
      <div className="graph-panel__toolbar" role="toolbar" aria-label="Graph mode">
        <button
          className={`graph-panel__mode-tab${mode === 'domain' ? ' graph-panel__mode-tab--active' : ''}`}
          onClick={() => onModeChange('domain')}
          aria-pressed={mode === 'domain'}
        >
          Domain
        </button>
        <button
          className={`graph-panel__mode-tab${mode === 'entity' ? ' graph-panel__mode-tab--active' : ''}`}
          onClick={() => onModeChange('entity')}
          aria-pressed={mode === 'entity'}
        >
          Entity
        </button>
        <button
          className={`graph-panel__mode-tab${mode === 'projection' ? ' graph-panel__mode-tab--active' : ''}`}
          onClick={() => onModeChange('projection')}
          aria-pressed={mode === 'projection'}
        >
          Projection
        </button>
        <button
          className={`graph-panel__mode-tab${mode === 'lineage' ? ' graph-panel__mode-tab--active' : ''}`}
          onClick={() => onModeChange('lineage')}
          aria-pressed={mode === 'lineage'}
        >
          Lineage
        </button>
        <span className="graph-panel__toolbar-spacer" />
        <button
          className="graph-panel__export-btn"
          onClick={exportSvg}
          disabled={nodes.length === 0}
        >
          Export SVG
        </button>
        <button
          className="graph-panel__export-btn"
          onClick={exportPng}
          disabled={nodes.length === 0}
        >
          Export PNG
        </button>
      </div>
      <div className="graph-panel__canvas" ref={containerRef}>
        {loading && (
          <div className="graph-panel__loading" aria-live="polite">
            Laying out graph...
          </div>
        )}
        {!loading && nodes.length === 0 && graphResult !== null && (
          <div className="graph-panel__empty" aria-live="polite">
            No graph data available
          </div>
        )}
        <ReactFlow
          nodes={nodesWithSelection}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodeClick={(_event, node) => onNodeClick(node as GraphNode)}
          fitView
          minZoom={0.1}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Controls />
          <MiniMap aria-hidden="true" />
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        </ReactFlow>
      </div>
    </div>
  );
}

export function GraphPanel(props: GraphPanelProps) {
  return (
    <ReactFlowProvider>
      <GraphPanelInner {...props} />
    </ReactFlowProvider>
  );
}
