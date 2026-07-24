import { useCallback, useEffect, useRef, useState } from 'react';

import type { BrowserCompilerClientLike } from '../client';
import type {
  BrowserCompatibilityResult,
  BrowserGovernanceResult,
  BrowserLineageResult,
} from '../protocol';

export interface AnalysisData {
  lineage: BrowserLineageResult | null;
  compatibility: BrowserCompatibilityResult | null;
  governance: BrowserGovernanceResult | null;
}

export interface UseAnalysisDataOptions {
  clientRef: React.RefObject<BrowserCompilerClientLike | null>;
  runtimeReady: boolean;
  workspaceRevisionRef: React.RefObject<number>;
}

export function useAnalysisData({
  clientRef,
  runtimeReady,
  workspaceRevisionRef,
}: UseAnalysisDataOptions): AnalysisData {
  const [data, setData] = useState<AnalysisData>({
    lineage: null,
    compatibility: null,
    governance: null,
  });
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

  const fetchAnalysis = useCallback(() => {
    const client = clientRef.current;
    if (client === null || !runtimeReady) return;
    const revision = workspaceRevisionRef.current;
    void Promise.all([
      client.lineage(revision),
      client.compatibility(revision),
      client.governance(revision),
    ]).then(
      ([lineage, compatibility, governance]) => {
        if (clientRef.current === client) {
          setData({ lineage, compatibility, governance });
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
        const id = requestIdleCallback(() => fetchAnalysis(), { timeout: 5000 });
        return () => cancelIdleCallback(id);
      }
      const id = setTimeout(fetchAnalysis, 1000);
      return () => clearTimeout(id);
    }
    fetchAnalysis();
  }, [fetchAnalysis, mounted]);

  return data;
}
