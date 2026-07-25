import ELK, { type ELK as ElkInstance, type ElkNode } from 'elkjs/lib/elk-api.js';
import ElkWorker from 'elkjs/lib/elk-worker.min.js?worker';

import type { LayoutRequest, LayoutResponse } from './graph-types';
import { applyLayout, buildElkGraph, type LayoutPosition } from './layout-model';

/**
 * ELK must be driven from a context that owns a real `Worker` constructor.
 * `elk.bundled.js` cannot be used inside a worker of our own: its in-thread
 * fallback ships in `elk-worker.min.js`, which only exports a fake `Worker`
 * class when `document` is defined, and installs itself as a worker entry
 * point otherwise. So we construct ELK here on the main thread and let it run
 * the layout in its own dedicated worker.
 */
let elk: ElkInstance | undefined;

function elkInstance(): ElkInstance {
  elk ??= new ELK({ workerFactory: () => new ElkWorker() });
  return elk;
}

export async function runLayout(
  request: LayoutRequest,
): Promise<LayoutResponse> {
  if (request.nodes.length === 0) {
    return { id: request.id, nodes: [], edges: [] };
  }
  const laidOut = await elkInstance().layout(
    buildElkGraph(request) as unknown as ElkNode,
  );
  const positions = new Map<string, LayoutPosition>();
  for (const child of laidOut.children ?? []) {
    positions.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 });
  }
  return applyLayout(request, positions);
}
