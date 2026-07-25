import { Handle, type NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';
import { handlePositions } from './handles';

export function DomainNode({ data }: NodeProps<GraphNode>) {
  const handles = handlePositions(data.direction);
  return (
    <div className="graph-node graph-node--domain">
      <Handle type="target" position={handles.target} />
      <div className="graph-node__label">
        <span className="graph-node__kind" aria-hidden="true">D</span>
        {data.label}
      </div>
      <Handle type="source" position={handles.source} />
    </div>
  );
}
