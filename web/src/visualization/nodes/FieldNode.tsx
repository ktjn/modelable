import { Handle, Position, type NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';

export function FieldNode({ data }: NodeProps<GraphNode>) {
  const optional = data.metadata.optional === true;
  return (
    <div className="graph-node graph-node--field" role="treeitem" aria-label={`Field: ${data.label}${optional ? ' (optional)' : ''}`}>
      <Handle type="target" position={Position.Top} />
      <div className="graph-node__label">
        <span className="graph-node__kind" aria-hidden="true">F</span>
        {data.label}{optional ? '?' : ''}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
