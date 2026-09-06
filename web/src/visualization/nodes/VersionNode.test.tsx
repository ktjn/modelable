// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import type { NodeProps } from '@xyflow/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import type { GraphNode } from '../graph-types';
import { VersionNode } from './VersionNode';

vi.mock('@xyflow/react', () => ({
  Handle: () => null,
  Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
}));

afterEach(() => {
  cleanup();
});

function props(metadata: Record<string, unknown>): NodeProps<GraphNode> {
  return {
    data: {
      label: 'Customer@2',
      kind: 'version',
      metadata,
      sourceRange: null,
      direction: 'RIGHT',
    },
  } as NodeProps<GraphNode>;
}

describe('VersionNode', () => {
  test('renders without a facet badge when metadata has no facets', () => {
    render(<VersionNode {...props({ version: 2, change_kind: 'additive' })} />);

    expect(screen.getByText(/v2/)).toBeTruthy();
    expect(screen.queryByTestId('graph-node-facets')).toBeNull();
  });

  test('renders a facet count badge with a value tooltip when facets are present', () => {
    render(
      <VersionNode
        {...props({
          version: 2,
          facets: [
            { identity: 'compliance.confidentiality', value: 'restricted', subject: 'model_version:sales.Customer@2', propagation: 'inherit', interpretation: 'known' },
          ],
        })}
      />,
    );

    const badge = screen.getByTestId('graph-node-facets');
    expect(badge.textContent).toBe('1f');
    expect(badge.getAttribute('title')).toContain('compliance.confidentiality');
    expect(badge.getAttribute('title')).toContain('restricted');
  });
});
