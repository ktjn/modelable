import { Handle } from '@xyflow/react';
import type { ReactNode } from 'react';

import type { LayoutDirection } from '../graph-types';
import type { BrowserFacetRecord } from '../../protocol';
import { handlePositions } from './handles';

export interface GraphNodeFrameProps {
  /** BEM modifier appended to `graph-node--`, e.g. `entity`. */
  variant: string;
  /** Single-letter kind badge shown before the label. */
  badge: string;
  direction: LayoutDirection;
  children: ReactNode;
  facets?: BrowserFacetRecord[];
}

/**
 * Shared chrome for every graph node: the flow handles on the sides the layout
 * runs between, plus the badge/label row. Node types only supply their label
 * content.
 */
export function GraphNodeFrame({
  variant,
  badge,
  direction,
  children,
  facets,
}: GraphNodeFrameProps) {
  const handles = handlePositions(direction);
  const facetCount = facets?.length ?? 0;
  const facetTitle =
    facetCount > 0
      ? (facets ?? []).map((facet) => `${facet.identity}: ${JSON.stringify(facet.value)}`).join('\n')
      : undefined;
  return (
    <div className={`graph-node graph-node--${variant}`}>
      <Handle type="target" position={handles.target} />
      <div className="graph-node__label">
        <span className="graph-node__kind" aria-hidden="true">
          {badge}
        </span>
        {children}
        {facetCount > 0 && (
          <span className="graph-node__facets" title={facetTitle} data-testid="graph-node-facets">
            {facetCount}f
          </span>
        )}
      </div>
      <Handle type="source" position={handles.source} />
    </div>
  );
}
