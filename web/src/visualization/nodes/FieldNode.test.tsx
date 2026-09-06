// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import type { NodeProps } from '@xyflow/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import type { GraphNode } from '../graph-types';
import { FieldNode } from './FieldNode';

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
      label: 'email',
      kind: 'field',
      metadata,
      sourceRange: null,
      direction: 'RIGHT',
    },
  } as NodeProps<GraphNode>;
}

describe('FieldNode', () => {
  test('renders without a facet badge when metadata has no facets', () => {
    render(<FieldNode {...props({ optional: false })} />);

    expect(screen.getByText('email')).toBeTruthy();
    expect(screen.queryByTestId('graph-node-facets')).toBeNull();
  });

  test('renders a facet count badge when facets are present', () => {
    render(
      <FieldNode
        {...props({
          optional: true,
          facets: [
            { identity: 'privacy.data-subject', value: true, subject: 'field:customer.CustomerRecord@1#email', propagation: 'project', interpretation: 'known' },
            { identity: 'privacy.retention-class', value: 'standard', subject: 'field:customer.CustomerRecord@1#email', propagation: 'project', interpretation: 'known' },
          ],
        })}
      />,
    );

    const badge = screen.getByTestId('graph-node-facets');
    expect(badge.textContent).toBe('2f');
    expect(badge.getAttribute('title')).toContain('privacy.data-subject');
    expect(badge.getAttribute('title')).toContain('privacy.retention-class');
  });
});
