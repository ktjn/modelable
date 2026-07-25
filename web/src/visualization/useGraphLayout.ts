import { useEffect, useRef, useState } from 'react';

import type { BrowserGraphResult } from '../protocol';
import { runLayout } from './elk-layout';
import type { GraphEdge, GraphNode, LayoutRequest } from './graph-types';

export interface GraphLayoutState {
  nodes: GraphNode[];
  edges: GraphEdge[];
  loading: boolean;
  error: string | null;
}

const emptyState: GraphLayoutState = {
  nodes: [],
  edges: [],
  loading: false,
  error: null,
};

export function useGraphLayout(
  graphResult: BrowserGraphResult | null,
): GraphLayoutState {
  const [state, setState] = useState<GraphLayoutState>(emptyState);
  const pendingIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (graphResult === null) {
      pendingIdRef.current = null;
      setState(emptyState);
      return;
    }

    const request: LayoutRequest = {
      id: `${graphResult.workspace_revision}-${graphResult.mode}-${Date.now()}`,
      nodes: graphResult.graph.nodes,
      edges: graphResult.graph.edges,
      mode: graphResult.mode,
    };
    pendingIdRef.current = request.id;
    setState((previous) => ({ ...previous, loading: true, error: null }));

    void runLayout(request).then(
      (response) => {
        if (pendingIdRef.current !== request.id) return;
        pendingIdRef.current = null;
        setState({
          nodes: response.nodes,
          edges: response.edges,
          loading: false,
          error: null,
        });
      },
      (error: unknown) => {
        if (pendingIdRef.current !== request.id) return;
        pendingIdRef.current = null;
        setState({
          nodes: [],
          edges: [],
          loading: false,
          error:
            error instanceof Error
              ? `Graph layout failed: ${error.message}`
              : 'Graph layout failed',
        });
      },
    );

    return () => {
      if (pendingIdRef.current === request.id) {
        pendingIdRef.current = null;
      }
    };
  }, [graphResult]);

  return state;
}
