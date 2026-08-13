// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { OutputPanel } from './OutputPanel';
import type { BrowserArtifact } from '../protocol';

vi.mock('../editor/ArtifactEditor', () => ({
  ArtifactEditor: ({ value }: { value: string }) => (
    <pre aria-label="Artifact output">{value}</pre>
  ),
}));

const artifacts: BrowserArtifact[] = [
  {
    path: 'customer.schema.json',
    media_type: 'application/schema+json',
    content: '{"title":"Customer"}',
    source_refs: ['file:///customer.mdl'],
  },
];

afterEach(cleanup);

beforeEach(() => {
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn(async () => undefined) },
  });
});

test('copies the selected artifact content and shows transient confirmation', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  render(
    <OutputPanel
      artifacts={artifacts}
      selectedArtifactPath="customer.schema.json"
      isStale={false}
      disabled={false}
      onSelect={vi.fn()}
      onDownload={vi.fn()}
      onDownloadAll={vi.fn()}
    />,
  );

  expect(screen.getAllByText('customer.schema.json')).toHaveLength(2);
  const copyButton = screen.getByRole('button', { name: 'Copy' });

  await fireEvent.click(copyButton);
  await vi.waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      '{"title":"Customer"}',
    ),
  );
  expect(
    await screen.findByRole('button', { name: 'Copied' }),
  ).toBeTruthy();

  act(() => {
    vi.advanceTimersByTime(1500);
  });
  expect(screen.getByRole('button', { name: 'Copy' })).toBeTruthy();
  vi.useRealTimers();
});

test('does not render a copy control when no artifact is selected', () => {
  render(
    <OutputPanel
      artifacts={[]}
      selectedArtifactPath={null}
      isStale={false}
      disabled={false}
      onSelect={vi.fn()}
      onDownload={vi.fn()}
      onDownloadAll={vi.fn()}
    />,
  );

  expect(screen.queryByRole('button', { name: 'Copy' })).toBeNull();
});
