import type { Node, Edge } from '@xyflow/react';

import type {
  BrowserGraphEdge,
  BrowserGraphMode,
  BrowserGraphNode,
  BrowserSourceRange,
} from '../protocol';

/** Direction the ELK layout flows in, which decides which sides handles sit on. */
export type LayoutDirection = 'DOWN' | 'RIGHT';

export interface GraphNodeData {
  label: string;
  kind: string;
  metadata: Record<string, unknown>;
  sourceRange: BrowserSourceRange | null;
  direction: LayoutDirection;
  [key: string]: unknown;
}

export type GraphNode = Node<GraphNodeData>;

export interface GraphEdgeData {
  kind: string;
  label: string | null;
  [key: string]: unknown;
}

export type GraphEdge = Edge<GraphEdgeData>;

export interface LayoutRequest {
  id: string;
  nodes: BrowserGraphNode[];
  edges: BrowserGraphEdge[];
  mode: BrowserGraphMode;
}

export interface LayoutResponse {
  id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}
