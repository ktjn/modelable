import { Handle, type NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';
import { handlePositions } from './handles';

export function FieldNode({ data }: NodeProps<GraphNode>) {
  const optional = data.metadata.optional === true;
  const handles = handlePositions(data.direction);
  return (
    <div className="graph-node graph-node--field">
      <Handle type="target" position={handles.target} />
      <div className="graph-node__label">
        <span className="graph-node__kind" aria-hidden="true">F</span>
        {data.label}{optional ? '?' : ''}
      </div>
      <Handle type="source" position={handles.source} />
    </div>
  );
}
