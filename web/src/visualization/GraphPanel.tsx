import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useRef } from 'react';

import type { BrowserGraphResult, BrowserGraphMode } from '../protocol';
import { INTERACTIVE_MIN_ZOOM } from './graph-viewport';
import type { GraphNode } from './graph-types';
import { useGraphExport } from './useGraphExport';
import { useGraphLayout } from './useGraphLayout';
import { useReadableGraphViewport } from './useReadableGraphViewport';
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
  const containerRef = useRef<HTMLDivElement>(null);
  const { exportSvg, exportPng } = useGraphExport(containerRef);
  const { nodes, edges, loading, error: layoutError } = useGraphLayout(
    graphResult,
  );
  const { fitViewOptions, showMiniMap, onMoveStart, onFitView } =
    useReadableGraphViewport(containerRef, nodes);
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

  return (
    <div className="graph-panel" role="region" aria-label="Model graph">
      <div className="tab-strip" role="toolbar" aria-label="Graph mode">
        <div className="graph-panel__modes">
          {(
            [
              ['domain', 'Domain'],
              ['entity', 'Entity'],
              ['projection', 'Projection'],
              ['lineage', 'Lineage'],
            ] as const
          ).map(([candidate, label]) => (
            <button
              key={candidate}
              className={`tab${mode === candidate ? ' tab--active' : ''}`}
              onClick={() => onModeChange(candidate)}
              aria-pressed={mode === candidate}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="graph-panel__exports">
          <button
            className="graph-panel__export-btn"
            onClick={exportSvg}
            disabled={nodes.length === 0}
            aria-label="Export SVG"
          >
            <span className="graph-panel__export-prefix">Export </span>SVG
          </button>
          <button
            className="graph-panel__export-btn"
            onClick={exportPng}
            disabled={nodes.length === 0}
            aria-label="Export PNG"
          >
            <span className="graph-panel__export-prefix">Export </span>PNG
          </button>
        </div>
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
          onMoveStart={onMoveStart}
          fitView
          fitViewOptions={fitViewOptions}
          minZoom={INTERACTIVE_MIN_ZOOM}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Controls
            orientation="horizontal"
            fitViewOptions={fitViewOptions}
            onFitView={onFitView}
          />
          {showMiniMap ? (
            <MiniMap
              aria-hidden="true"
              className="graph-panel__minimap"
              style={{ width: 144, height: 104 }}
            />
          ) : null}
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
