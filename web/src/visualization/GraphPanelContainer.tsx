import {
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';

import { BrowserCompilerError } from '../client';
import type { BrowserCompilerClientLike } from '../client';
import type { BrowserGraphMode, BrowserGraphResult } from '../protocol';

const GraphPanel = lazy(() =>
  import('./GraphPanel').then((m) => ({ default: m.GraphPanel })),
);

export interface GraphPanelContainerProps {
  clientRef: React.RefObject<BrowserCompilerClientLike | null>;
  runtimeReady: boolean;
  /**
   * The workspace revision the compiler's language workspace is synchronized
   * to, or null before the first synchronization. Asking for a graph at any
   * other revision is rejected as stale, so this — not the editor's current
   * revision — is what drives a refetch.
   */
  languageRevision: number | null;
}

export const GraphPanelContainer = memo(function GraphPanelContainer({
  clientRef,
  runtimeReady,
  languageRevision,
}: GraphPanelContainerProps) {
  const [graphResult, setGraphResult] =
    useState<BrowserGraphResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [graphMode, setGraphMode] = useState<BrowserGraphMode>('domain');
  const [mounted, setMounted] = useState(false);
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
    if (client === null || !runtimeReady || languageRevision === null) return;
    void client.graph(languageRevision, graphMode).then(
      (result) => {
        if (clientRef.current !== client) return;
        setGraphResult(result);
        setError(null);
      },
      (reason: unknown) => {
        if (clientRef.current !== client) return;
        // A newer revision was synchronized while this request was in flight;
        // the fetch for that revision is already on its way.
        if (
          reason instanceof BrowserCompilerError &&
          reason.code === 'STALE_WORKSPACE'
        ) {
          return;
        }
        setError(
          reason instanceof Error
            ? `Graph unavailable: ${reason.message}`
            : 'Graph unavailable',
        );
      },
    );
  }, [clientRef, graphMode, languageRevision, runtimeReady]);

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
  }, [fetchGraph, mounted]);

  if (!mounted) return null;

  return (
    <Suspense fallback={null}>
      <GraphPanel
        graphResult={graphResult}
        mode={graphMode}
        onModeChange={setGraphMode}
        error={error}
      />
    </Suspense>
  );
});
