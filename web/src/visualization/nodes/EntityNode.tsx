import type { NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';
import { GraphNodeFrame } from './GraphNodeFrame';

export function EntityNode({ data }: NodeProps<GraphNode>) {
  return (
    <GraphNodeFrame variant="entity" badge="E" direction={data.direction}>
      {data.label}
    </GraphNodeFrame>
  );
}
