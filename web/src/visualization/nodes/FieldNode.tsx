import type { NodeProps } from '@xyflow/react';

import { facetsFromMetadata, type GraphNode } from '../graph-types';
import { GraphNodeFrame } from './GraphNodeFrame';

export function FieldNode({ data }: NodeProps<GraphNode>) {
  const optional = data.metadata.optional === true;
  return (
    <GraphNodeFrame
      variant="field"
      badge="F"
      direction={data.direction}
      facets={facetsFromMetadata(data.metadata)}
    >
      {data.label}
      {optional ? '?' : ''}
    </GraphNodeFrame>
  );
}
