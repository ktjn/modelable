import type { NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';
import { GraphNodeFrame } from './GraphNodeFrame';

export function VersionNode({ data }: NodeProps<GraphNode>) {
  const version = data.metadata.version;
  const changeKind = data.metadata.change_kind;
  const suffix = changeKind ? ` (${changeKind})` : '';
  return (
    <GraphNodeFrame variant="version" badge="V" direction={data.direction}>
      v{String(version ?? data.label)}
      {suffix}
    </GraphNodeFrame>
  );
}
