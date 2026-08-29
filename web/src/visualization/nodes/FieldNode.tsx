import type { NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';
import { GraphNodeFrame } from './GraphNodeFrame';

export function FieldNode({ data }: NodeProps<GraphNode>) {
  const optional = data.metadata.optional === true;
  return (
    <GraphNodeFrame variant="field" badge="F" direction={data.direction}>
      {data.label}
      {optional ? '?' : ''}
    </GraphNodeFrame>
  );
}
