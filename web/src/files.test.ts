// @vitest-environment jsdom

import { describe, expect, test, vi } from 'vitest';

import {
  MAX_IMPORT_BYTES,
  downloadText,
  readSourceFile,
  sanitizeDownloadName,
} from './files';

describe('local file boundary', () => {
  test.each(['schema.exe', 'schema.json', 'schema'])(
    'rejects unsupported import %s',
    async (name) => {
      await expect(readSourceFile(new File(['text'], name))).rejects.toThrow(
        /\.mdl or \.txt/i,
      );
    },
  );

  test('rejects files above the exact size limit', async () => {
    const file = new File(
      [new Uint8Array(MAX_IMPORT_BYTES + 1)],
      'large.mdl',
    );
    await expect(readSourceFile(file)).rejects.toThrow(/1 MiB/i);
  });

  test('sanitizes an untrusted download filename', () => {
    expect(sanitizeDownloadName('../Customer<>', '.mdl')).toBe(
      'Customer.mdl',
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
