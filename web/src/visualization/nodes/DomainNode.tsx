import type { NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';
import { GraphNodeFrame } from './GraphNodeFrame';

export function DomainNode({ data }: NodeProps<GraphNode>) {
  return (
    <GraphNodeFrame variant="domain" badge="D" direction={data.direction}>
      {data.label}
    </GraphNodeFrame>
  );
}
