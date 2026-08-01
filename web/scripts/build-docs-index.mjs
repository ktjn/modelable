import { rm, mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const cliRoot = resolve(webRoot, '..', 'cli');
const docsRoot = resolve(webRoot, '..', 'docs');
const output = join(webRoot, 'public', 'docs-index');

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

await new Promise((resolve, reject) => {
  const child = spawn(process.platform === 'win32' ? 'uv.exe' : 'uv', [
    'run', '--project', cliRoot, 'modelable', 'docs-index', docsRoot,
    '--out', output,
    '--base-url', 'https://ktjn.github.io/modelable/',
  ], { cwd: webRoot, stdio: 'inherit' });
  child.on('error', reject);
  child.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`docs-index exited with ${code}`)));
});
