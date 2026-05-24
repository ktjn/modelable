import * as path from 'path';
import { runTests } from '@vscode/test-electron';

async function main(): Promise<void> {
  // __dirname compiles to vscode/out/test/
  const extensionDevelopmentPath = path.resolve(__dirname, '../..');
  const extensionTestsPath = path.resolve(__dirname, './suite/index');
  const workspaceFolder = path.resolve(
    __dirname,
    '../../../samples/scenarios/04-credit-risk-feature-store',
  );

  await runTests({
    extensionDevelopmentPath,
    extensionTestsPath,
    launchArgs: [workspaceFolder],
  });
}

main().catch(err => {
  console.error('Failed to run VS Code tests:', err);
  process.exit(1);
});
