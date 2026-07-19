export const MAX_IMPORT_BYTES = 1_048_576;

export interface ObjectUrlApi {
  createObjectURL(blob: Blob): string;
  revokeObjectURL(url: string): void;
}

export async function readSourceFile(
  file: File,
): Promise<{ name: string; text: string }> {
  if (!/\.(?:mdl|txt)$/i.test(file.name)) {
    throw new Error('Choose a .mdl or .txt source file');
  }
  if (file.size > MAX_IMPORT_BYTES) {
    throw new Error('Source files must be 1 MiB or smaller');
  }
  return { name: file.name, text: await file.text() };
}

export function sanitizeDownloadName(
  name: string,
  extension: '.mdl' | '.json',
) {
  const basename = name.split(/[\\/]/).at(-1) ?? name;
  const sanitizedStem =
    basename
      .normalize('NFKC')
      .replace(/\.[^.]+$/, '')
      .replace(/[^a-zA-Z0-9._-]+/g, '-')
      .replace(/^[.-]+|[.-]+$/g, '')
      .slice(0, 96) || 'modelable';
  const stem =
    /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(
      sanitizedStem,
    )
      ? `_${sanitizedStem}`
      : sanitizedStem;
  return `${stem}${extension}`;
}

export function downloadText(
  text: string,
  filename: string,
  mediaType: string,
  objectUrls: ObjectUrlApi = URL,
): void {
  const url = objectUrls.createObjectURL(
    new Blob([text], { type: mediaType }),
  );
  const anchor = document.createElement('a');
  try {
    anchor.href = url;
    anchor.download = filename;
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    objectUrls.revokeObjectURL(url);
  }
}
