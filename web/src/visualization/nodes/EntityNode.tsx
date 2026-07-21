import { Handle, Position, type NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';

export function EntityNode({ data }: NodeProps<GraphNode>) {
  return (
    <div className="graph-node graph-node--entity" role="treeitem" aria-label={`Entity: ${data.label}`}>
      <Handle type="target" position={Position.Top} />
      <div className="graph-node__label">{data.label}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
