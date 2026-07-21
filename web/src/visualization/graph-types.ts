import type { Node, Edge } from '@xyflow/react';

import type {
  BrowserGraphEdge,
  BrowserGraphMode,
  BrowserGraphNode,
  BrowserSourceRange,
} from '../protocol';

export interface GraphNodeData {
  label: string;
  kind: string;
  metadata: Record<string, unknown>;
  sourceRange: BrowserSourceRange | null;
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

export interface LayoutError {
  id: string;
  error: string;
}

export type LayoutWorkerResponse = LayoutResponse | LayoutError;

export function isLayoutError(
  response: LayoutWorkerResponse,
): response is LayoutError {
  return 'error' in response;
}
