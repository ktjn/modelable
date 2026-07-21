import { Handle, Position, type NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';

export function ProjectionNode({ data }: NodeProps<GraphNode>) {
  return (
    <div className="graph-node graph-node--projection" role="treeitem" aria-label={`Projection: ${data.label}`}>
      <Handle type="target" position={Position.Top} />
      <div className="graph-node__label">
        <span className="graph-node__kind" aria-hidden="true">P</span>
        {data.label}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
