import { useCallback, useEffect, useRef, useState } from 'react';

import type { BrowserGraphResult } from '../protocol';
import type {
  GraphEdge,
  GraphNode,
  LayoutRequest,
  LayoutWorkerResponse,
} from './graph-types';
import { isLayoutError } from './graph-types';

export interface GraphLayoutState {
  nodes: GraphNode[];
  edges: GraphEdge[];
  loading: boolean;
}

export function useGraphLayout(
  graphResult: BrowserGraphResult | null,
): GraphLayoutState {
  const [state, setState] = useState<GraphLayoutState>({
    nodes: [],
    edges: [],
    loading: false,
  });
  const workerRef = useRef<Worker | null>(null);
  const pendingIdRef = useRef<string | null>(null);

  useEffect(() => {
    const worker = new Worker(
      new URL('./layout.worker.ts', import.meta.url),
      { type: 'module' },
    );
    workerRef.current = worker;

    const handleMessage = (event: MessageEvent<LayoutWorkerResponse>) => {
      const response = event.data;
      if (response.id !== pendingIdRef.current) return;
      pendingIdRef.current = null;
      if (isLayoutError(response)) {
        setState({ nodes: [], edges: [], loading: false });
        return;
      }
      setState({ nodes: response.nodes, edges: response.edges, loading: false });
    };

    worker.addEventListener('message', handleMessage);
    return () => {
      worker.removeEventListener('message', handleMessage);
      worker.terminate();
      workerRef.current = null;
    };
  }, []);

  const requestLayout = useCallback(
    (result: BrowserGraphResult) => {
      const worker = workerRef.current;
      if (worker === null) return;
      const id = `${result.workspace_revision}-${result.mode}-${Date.now()}`;
      pendingIdRef.current = id;
      setState((prev) => ({ ...prev, loading: true }));
      const request: LayoutRequest = {
        id,
        nodes: result.graph.nodes,
        edges: result.graph.edges,
        mode: result.mode,
      };
      worker.postMessage(request);
    },
    [],
  );

  useEffect(() => {
    if (graphResult !== null) {
      requestLayout(graphResult);
    } else {
      setState({ nodes: [], edges: [], loading: false });
    }
  }, [graphResult, requestLayout]);

  return state;
}
