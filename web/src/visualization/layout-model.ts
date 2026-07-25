import type { BrowserGraphMode } from '../protocol';
import type {
  GraphEdge,
  GraphNode,
  LayoutDirection,
  LayoutRequest,
  LayoutResponse,
} from './graph-types';

export interface ElkLayoutNode {
  id: string;
  width: number;
  height: number;
}

export interface ElkLayoutEdge {
  id: string;
  sources: string[];
  targets: string[];
}

export interface ElkLayoutGraph {
  id: string;
  layoutOptions: Record<string, string>;
  children: ElkLayoutNode[];
  edges: ElkLayoutEdge[];
}

export interface LayoutPosition {
  x: number;
  y: number;
}

const NODE_WIDTH = 180;
const NODE_HEIGHT = 40;
const FIELD_NODE_HEIGHT = 28;
const VERSION_NODE_HEIGHT = 32;

export function nodeSize(kind: string): { width: number; height: number } {
  if (kind === 'field') return { width: NODE_WIDTH, height: FIELD_NODE_HEIGHT };
  if (kind === 'version')
    return { width: NODE_WIDTH, height: VERSION_NODE_HEIGHT };
  return { width: NODE_WIDTH, height: NODE_HEIGHT };
}

export function layoutDirection(mode: BrowserGraphMode): LayoutDirection {
  return mode === 'entity' ? 'DOWN' : 'RIGHT';
}

export function buildElkGraph(request: LayoutRequest): ElkLayoutGraph {
  return {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': layoutDirection(request.mode),
      'elk.spacing.nodeNode': '30',
      'elk.layered.spacing.nodeNodeBetweenLayers': '60',
      'elk.padding': '[top=20,left=20,bottom=20,right=20]',
    },
    children: request.nodes.map((node) => ({
      id: node.id,
      ...nodeSize(node.kind),
    })),
    edges: request.edges.map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
    })),
  };
}

export function applyLayout(
  request: LayoutRequest,
  positions: Map<string, LayoutPosition>,
): LayoutResponse {
  const direction = layoutDirection(request.mode);
  const nodes: GraphNode[] = request.nodes.map((node) => {
    const size = nodeSize(node.kind);
    return {
      id: node.id,
      type: node.kind,
      position: positions.get(node.id) ?? { x: 0, y: 0 },
      data: {
        label: node.label,
        kind: node.kind,
        metadata: node.metadata,
        sourceRange: node.source_range,
        direction,
      },
      width: size.width,
      height: size.height,
    };
  });

  const edges: GraphEdge[] = request.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: edge.kind,
    data: {
      kind: edge.kind,
      label: edge.label,
    },
  }));

  return { id: request.id, nodes, edges };
}
