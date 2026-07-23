import ELK, { type ElkNode, type ElkExtendedEdge } from 'elkjs/lib/elk.bundled.js';

import type {
  GraphEdge,
  GraphNode,
  LayoutRequest,
  LayoutWorkerResponse,
} from './graph-types';

const elk = new ELK();

const NODE_WIDTH = 180;
const NODE_HEIGHT = 40;
const FIELD_NODE_HEIGHT = 28;
const VERSION_NODE_HEIGHT = 32;

function nodeSize(kind: string): { width: number; height: number } {
  if (kind === 'field') return { width: NODE_WIDTH, height: FIELD_NODE_HEIGHT };
  if (kind === 'version')
    return { width: NODE_WIDTH, height: VERSION_NODE_HEIGHT };
  return { width: NODE_WIDTH, height: NODE_HEIGHT };
}

async function layout(request: LayoutRequest): Promise<LayoutWorkerResponse> {
  const elkNodes: ElkNode[] = request.nodes.map((node) => {
    const size = nodeSize(node.kind);
    return {
      id: node.id,
      width: size.width,
      height: size.height,
    };
  });

  const elkEdges: ElkExtendedEdge[] = request.edges.map((edge) => ({
    id: edge.id,
    sources: [edge.source],
    targets: [edge.target],
  }));

  const graph: ElkNode = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': request.mode === 'entity' ? 'DOWN' : 'RIGHT',
      'elk.spacing.nodeNode': '30',
      'elk.layered.spacing.nodeNodeBetweenLayers': '60',
      'elk.padding': '[top=20,left=20,bottom=20,right=20]',
    },
    children: elkNodes,
    edges: elkEdges,
  };

  const result = await elk.layout(graph);

  const positionMap = new Map<string, { x: number; y: number }>();
  for (const child of result.children ?? []) {
    positionMap.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 });
  }

  const nodes: GraphNode[] = request.nodes.map((node) => {
    const position = positionMap.get(node.id) ?? { x: 0, y: 0 };
    const size = nodeSize(node.kind);
    return {
      id: node.id,
      type: node.kind,
      position,
      data: {
        label: node.label,
        kind: node.kind,
        metadata: node.metadata,
        sourceRange: node.source_range,
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

self.addEventListener('message', (event: MessageEvent<LayoutRequest>) => {
  layout(event.data)
    .then((response) => self.postMessage(response))
    .catch((error: unknown) => {
      const message =
        error instanceof Error ? error.message : 'Layout failed';
      self.postMessage({
        id: event.data.id,
        error: message,
      } satisfies LayoutWorkerResponse);
    });
});
