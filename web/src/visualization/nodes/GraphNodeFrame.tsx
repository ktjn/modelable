import { Handle } from '@xyflow/react';
import type { ReactNode } from 'react';

import type { LayoutDirection } from '../graph-types';
import { handlePositions } from './handles';

export interface GraphNodeFrameProps {
  /** BEM modifier appended to `graph-node--`, e.g. `entity`. */
  variant: string;
  /** Single-letter kind badge shown before the label. */
  badge: string;
  direction: LayoutDirection;
  children: ReactNode;
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
}: GraphNodeFrameProps) {
  const handles = handlePositions(direction);
  return (
    <div className={`graph-node graph-node--${variant}`}>
      <Handle type="target" position={handles.target} />
      <div className="graph-node__label">
        <span className="graph-node__kind" aria-hidden="true">
          {badge}
        </span>
        {children}
      </div>
      <Handle type="source" position={handles.source} />
    </div>
  );
}
