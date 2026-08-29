import type { NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';
import { GraphNodeFrame } from './GraphNodeFrame';

export function ProjectionNode({ data }: NodeProps<GraphNode>) {
  return (
    <GraphNodeFrame variant="projection" badge="P" direction={data.direction}>
      {data.label}
    </GraphNodeFrame>
  );
}
