import { BaseEdge, getStraightPath, type EdgeProps } from '@xyflow/react';

import type { GraphEdge } from '../graph-types';

export function ContainsEdge(props: EdgeProps<GraphEdge>) {
  const [edgePath] = getStraightPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
  });
  return (
    <BaseEdge
      id={props.id}
      path={edgePath}
      className="graph-edge graph-edge--contains"
      aria-label="contains"
    />
  );
}
