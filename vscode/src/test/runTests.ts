import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { spawnSync } from 'child_process';
import { runTests } from '@vscode/test-electron';

async function main(): Promise<void> {
  ensureDesktopCodeIsClosed();

  // __dirname compiles to vscode/out/test/
  const extensionDevelopmentPath = path.resolve(__dirname, '../..');
  const extensionTestsPath = path.resolve(__dirname, './suite/index');
  const workspaceFolder = path.resolve(
    __dirname,
    '../../../samples/scenarios/04-credit-risk-feature-store',
  );
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'modelable-vscode-'));
  const settingsDir = path.join(userDataDir, 'User');
  fs.mkdirSync(settingsDir, { recursive: true });
  fs.writeFileSync(
    path.join(settingsDir, 'settings.json'),
    JSON.stringify({ 'update.mode': 'none' }, null, 2),
  );

  await runTests({
    extensionDevelopmentPath,
    extensionTestsPath,
    launchArgs: ['--user-data-dir', userDataDir, workspaceFolder],
  });
}

function ensureDesktopCodeIsClosed(): void {
  if (process.platform !== 'win32') {
    return;
  }

  const result = spawnSync('tasklist', ['/FI', 'IMAGENAME eq Code.exe', '/NH'], {
    encoding: 'utf-8',
  });
  if (result.error) {
    return;
  }

  const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
  if (output.includes('Code.exe')) {
    throw new Error(
      'Close all running VS Code windows before running `npm test` in vscode/. ' +
        'The smoke harness needs an unlocked VS Code installation on Windows.',
    );
  }
}

main().catch(err => {
  console.error('Failed to run VS Code tests:', err);
  process.exit(1);
});
