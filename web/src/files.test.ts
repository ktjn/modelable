// @vitest-environment jsdom

import { describe, expect, test, vi } from 'vitest';

import {
  MAX_IMPORT_BYTES,
  downloadRecoveryData,
  downloadText,
  readWorkspaceFiles,
  sanitizeDownloadName,
} from './files';

describe('local file boundary', () => {
  test('reads multiple mdl files in deterministic name order', async () => {
    const files = [
      new File(['domain z {}'], 'z.mdl', { type: 'text/plain' }),
      new File(['domain a {}'], 'a.mdl', { type: 'text/plain' }),
    ];
    await expect(readWorkspaceFiles(files)).resolves.toEqual([
      { path: 'a.mdl', content: 'domain a {}' },
      { path: 'z.mdl', content: 'domain z {}' },
    ]);
  });

  test('rejects non-mdl, oversized, and duplicate normalized names', async () => {
    await expect(
      readWorkspaceFiles([new File(['x'], 'source.txt')]),
    ).rejects.toThrow('Choose .mdl workspace files');
    await expect(
      readWorkspaceFiles([
        new File(
          [new Uint8Array(MAX_IMPORT_BYTES + 1)],
          'large.mdl',
        ),
      ]),
    ).rejects.toThrow('Workspace files must be 1 MiB or smaller');
    await expect(
      readWorkspaceFiles([
        new File(['a'], 'same.mdl'),
        new File(['b'], 'same.mdl'),
      ]),
    ).rejects.toThrow('Choose files with unique workspace paths');
  });

  test('sanitizes an untrusted download filename', () => {
    expect(sanitizeDownloadName('../Customer<>', '.mdl')).toBe(
      'Customer.mdl',
    );
  });

  test('downloads raw recovery data without rendering it', () => {
    const download = vi.fn();
    downloadRecoveryData({ source: '<script>x</script>' }, download);
    expect(download).toHaveBeenCalledWith(
      '{\n  "source": "<script>x</script>"\n}',
      'modelable-playground-recovery.json',
      'application/json',
    );
  });

  test.each([
    ['/tmp/Customer.mdl', '.mdl', 'Customer.mdl'],
    ['C:\\exports\\Order.json', '.json', 'Order.json'],
  ] as const)(
    'uses only the basename from %s',
    (name, extension, expected) => {
      expect(sanitizeDownloadName(name, extension)).toBe(expected);
    },
  );

  test.each([
    'cOn',
    'PrN',
    'aUx',
    'NuL',
    ...Array.from({ length: 9 }, (_, index) => `cOm${index + 1}`),
    ...Array.from({ length: 9 }, (_, index) => `LpT${index + 1}`),
  ])('prefixes reserved device name %s case-insensitively', (device) => {
    const separator = device.length % 2 === 0 ? '/' : '\\';
    expect(
      sanitizeDownloadName(
        `tmp${separator}${device}.txt`,
        '.mdl',
      ),
    ).toBe(`_${device}.mdl`);
  });

  test('prefixes a reserved device stem even with extensions', () => {
    expect(
      sanitizeDownloadName('C:\\exports\\CON.report.json', '.json'),
    ).toBe('_CON.report.json');
  });

  test('revokes the object URL after starting a download', () => {
    const createObjectURL = vi.fn(() => 'blob:test');
    const revokeObjectURL = vi.fn();
    downloadText('source', 'main.mdl', 'text/plain', {
      createObjectURL,
      revokeObjectURL,
    });
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test');
  });
});
