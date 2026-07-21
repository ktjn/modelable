import { useCallback, useMemo } from 'react';

import type { BrowserSourceRange } from '../protocol';
import type { GraphNode } from './graph-types';

export interface GraphSyncResult {
  selectedNodeId: string | null;
  onNodeClick: (node: GraphNode) => void;
}

export function useGraphSync(
  nodes: GraphNode[],
  cursorUri: string | null,
  cursorLine: number | null,
  onRevealRange?: (uri: string, line: number, character: number) => void,
): GraphSyncResult {
  const selectedNodeId = useMemo(() => {
    if (cursorUri === null || cursorLine === null) return null;
    for (const node of nodes) {
      const range = node.data.sourceRange;
      if (range === null) continue;
      if (
        range.uri === cursorUri &&
        cursorLine >= range.start_line &&
        cursorLine <= range.end_line
      ) {
        return node.id;
      }
    }
    return null;
  }, [nodes, cursorUri, cursorLine]);

  const onNodeClick = useCallback(
    (node: GraphNode) => {
      const range: BrowserSourceRange | null = node.data.sourceRange;
      if (range === null || onRevealRange === undefined) return;
      onRevealRange(range.uri, range.start_line, range.start_character);
    },
    [onRevealRange],
  );

  return { selectedNodeId, onNodeClick };
}
