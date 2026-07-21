import {
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';

import type { BrowserCompilerClientLike } from '../client';
import type { BrowserGraphMode, BrowserGraphResult } from '../protocol';

const GraphPanel = lazy(() =>
  import('./GraphPanel').then((m) => ({ default: m.GraphPanel })),
);

export interface GraphPanelContainerProps {
  clientRef: React.RefObject<BrowserCompilerClientLike | null>;
  runtimeReady: boolean;
  workspaceRevisionRef: React.RefObject<number>;
}

export const GraphPanelContainer = memo(function GraphPanelContainer({
  clientRef,
  runtimeReady,
  workspaceRevisionRef,
}: GraphPanelContainerProps) {
  const [graphResult, setGraphResult] =
    useState<BrowserGraphResult | null>(null);
  const [graphMode, setGraphMode] = useState<BrowserGraphMode>('domain');
  const [mounted, setMounted] = useState(false);
  const graphModeRef = useRef(graphMode);
  graphModeRef.current = graphMode;
  const initialFetchDone = useRef(false);

  useEffect(() => {
    if (!runtimeReady || mounted) return;
    let cancelled = false;
    const id = setTimeout(() => {
      if (!cancelled) setMounted(true);
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [runtimeReady, mounted]);

  const fetchGraph = useCallback(() => {
    const client = clientRef.current;
    if (client === null || !runtimeReady) return;
    void client
      .graph(workspaceRevisionRef.current, graphModeRef.current)
      .then(
        (result) => {
          if (clientRef.current === client) {
            setGraphResult(result);
          }
        },
        () => {},
      );
  }, [clientRef, runtimeReady, workspaceRevisionRef]);

  useEffect(() => {
    if (!mounted) return;
    if (!initialFetchDone.current) {
      initialFetchDone.current = true;
      if (typeof requestIdleCallback === 'function') {
        const id = requestIdleCallback(() => fetchGraph(), { timeout: 5000 });
        return () => cancelIdleCallback(id);
      }
      const id = setTimeout(fetchGraph, 1000);
      return () => clearTimeout(id);
    }
    fetchGraph();
  }, [fetchGraph, graphMode, mounted]);

  if (!mounted) return null;

  return (
    <Suspense fallback={null}>
      <GraphPanel
        graphResult={graphResult}
        mode={graphMode}
        onModeChange={setGraphMode}
      />
    </Suspense>
  );
});
