import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useEffect } from 'react';

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
  error?: string | null;
  cursorUri?: string | null;
  cursorLine?: number | null;
  onRevealRange?: (uri: string, line: number, character: number) => void;
}

function GraphPanelInner({
  graphResult,
  mode,
  onModeChange,
  error = null,
  cursorUri = null,
  cursorLine = null,
  onRevealRange,
}: GraphPanelProps) {
  const { containerRef, exportSvg, exportPng } = useGraphExport();
  const { nodes, edges, loading, error: layoutError } = useGraphLayout(
    graphResult,
  );
  const failure = error ?? layoutError;
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

  // Nodes arrive after the first render, so the `fitView` prop alone only ever
  // fits an empty canvas. Refit once each new layout has been painted.
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (nodes.length === 0) return;
    const frame = requestAnimationFrame(() => {
      void fitView();
    });
    return () => cancelAnimationFrame(frame);
  }, [fitView, nodes]);

  return (
    <div className="graph-panel" role="region" aria-label="Model graph">
      <div className="tab-strip" role="toolbar" aria-label="Graph mode">
        <button
          className={`tab${mode === 'domain' ? ' tab--active' : ''}`}
          onClick={() => onModeChange('domain')}
          aria-pressed={mode === 'domain'}
        >
          Domain
        </button>
        <button
          className={`tab${mode === 'entity' ? ' tab--active' : ''}`}
          onClick={() => onModeChange('entity')}
          aria-pressed={mode === 'entity'}
        >
          Entity
        </button>
        <button
          className={`tab${mode === 'projection' ? ' tab--active' : ''}`}
          onClick={() => onModeChange('projection')}
          aria-pressed={mode === 'projection'}
        >
          Projection
        </button>
        <button
          className={`tab${mode === 'lineage' ? ' tab--active' : ''}`}
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
        {failure !== null && (
          <div className="graph-panel__error" role="alert">
            {failure}
          </div>
        )}
        {failure === null && loading && (
          <div className="graph-panel__loading" aria-live="polite">
            Laying out graph...
          </div>
        )}
        {failure === null &&
          !loading &&
          nodes.length === 0 &&
          graphResult !== null && (
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
