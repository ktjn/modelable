import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { runTests } from '@vscode/test-electron';

// Pass MODELABLE_VSCODE_NO_HEADLESS=1 to run with a visible window (useful for
// interactive debugging). By default tests run headlessly so they work alongside
// a running VS Code desktop instance and in CI without a display server.
const headless = process.env['MODELABLE_VSCODE_NO_HEADLESS'] !== '1';

async function main(): Promise<void> {
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

  const extraArgs = headless ? ['--headless', '--disable-gpu'] : [];

  await runTests({
    extensionDevelopmentPath,
    extensionTestsPath,
    launchArgs: [...extraArgs, '--user-data-dir', userDataDir, workspaceFolder],
  });
}

main().catch(err => {
  console.error('Failed to run VS Code tests:', err);
  process.exit(1);
});
