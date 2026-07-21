import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react';

import type { GraphEdge } from '../graph-types';

export function ProjectsEdge(props: EdgeProps<GraphEdge>) {
  const [edgePath] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
  });
  return (
    <BaseEdge
      id={props.id}
      path={edgePath}
      className="graph-edge graph-edge--projects"
      style={{ strokeDasharray: '6 3' }}
      aria-label="projects"
    />
  );
}
