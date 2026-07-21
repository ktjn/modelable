import type { EdgeTypes, NodeTypes } from '@xyflow/react';

import { ContainsEdge } from './edges/ContainsEdge';
import { ProjectsEdge } from './edges/ProjectsEdge';
import { DomainNode } from './nodes/DomainNode';
import { EntityNode } from './nodes/EntityNode';
import { FieldNode } from './nodes/FieldNode';
import { ProjectionNode } from './nodes/ProjectionNode';
import { VersionNode } from './nodes/VersionNode';

export const nodeTypes: NodeTypes = {
  domain: DomainNode,
  entity: EntityNode,
  version: VersionNode,
  field: FieldNode,
  projection: ProjectionNode,
};

export const edgeTypes: EdgeTypes = {
  contains: ContainsEdge,
  projects: ProjectsEdge,
};
