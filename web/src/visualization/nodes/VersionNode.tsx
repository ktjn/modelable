import { Handle, type NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';
import { handlePositions } from './handles';

export function VersionNode({ data }: NodeProps<GraphNode>) {
  const version = data.metadata.version;
  const changeKind = data.metadata.change_kind;
  const suffix = changeKind ? ` (${changeKind})` : '';
  const handles = handlePositions(data.direction);
  return (
    <div className="graph-node graph-node--version" role="treeitem" aria-label={`Version ${version}${suffix}`}>
      <Handle type="target" position={handles.target} />
      <div className="graph-node__label">
        <span className="graph-node__kind" aria-hidden="true">V</span>
        v{String(version ?? data.label)}{suffix}
      </div>
      <Handle type="source" position={handles.source} />
    </div>
  );
}
