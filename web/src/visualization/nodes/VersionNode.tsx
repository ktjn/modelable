import { Handle, Position, type NodeProps } from '@xyflow/react';

import type { GraphNode } from '../graph-types';

export function VersionNode({ data }: NodeProps<GraphNode>) {
  const version = data.metadata.version;
  const changeKind = data.metadata.change_kind;
  const suffix = changeKind ? ` (${changeKind})` : '';
  return (
    <div className="graph-node graph-node--version" role="treeitem" aria-label={`Version ${version}${suffix}`}>
      <Handle type="target" position={Position.Top} />
      <div className="graph-node__label">
        v{String(version ?? data.label)}{suffix}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
