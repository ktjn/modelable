import { rm, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { spawn } from 'node:child_process';

const webRoot = new URL('..', import.meta.url).pathname.replace(/^\//, '').replaceAll('/', '\\');
const output = join(webRoot, 'public', 'docs-index');

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

await new Promise((resolve, reject) => {
  const child = spawn('uv', [
    'run', '--project', '../cli', 'modelable', 'docs-index', '../docs',
    '--out', 'public/docs-index',
    '--base-url', 'https://ktjn.github.io/modelable/',
  ], { cwd: webRoot, stdio: 'inherit', shell: process.platform === 'win32' });
  child.on('error', reject);
  child.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`docs-index exited with ${code}`)));
});
