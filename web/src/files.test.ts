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
