import * as vscode from 'vscode';
import * as assert from 'assert';

function waitForDiagnostics(uri: vscode.Uri, timeoutMs = 15_000): Promise<vscode.Diagnostic[]> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`Timeout (${timeoutMs}ms) waiting for diagnostics on ${uri.fsPath}`)),
      timeoutMs,
    );
    const sub = vscode.languages.onDidChangeDiagnostics(e => {
      if (e.uris.some(u => u.toString() === uri.toString())) {
        clearTimeout(timer);
        sub.dispose();
        resolve(vscode.languages.getDiagnostics(uri));
      }
    });
  });
}

async function completionLabels(uri: vscode.Uri, position: vscode.Position): Promise<string[]> {
  const results = await vscode.commands.executeCommand<vscode.CompletionList | vscode.CompletionItem[]>(
    'vscode.executeCompletionItemProvider',
    uri,
    position,
  );
  if (!results) {
    return [];
  }

  const items = Array.isArray(results) ? results : results.items;
  return items.map(item => item.label.toString());
}

async function documentSymbolNames(uri: vscode.Uri): Promise<string[]> {
  const results = await vscode.commands.executeCommand<
    vscode.DocumentSymbol[] | vscode.SymbolInformation[]
  >('vscode.executeDocumentSymbolProvider', uri);
  if (!results) {
    return [];
  }

  const symbols = results as vscode.DocumentSymbol[];
  const names: string[] = [];

  const visit = (symbol: vscode.DocumentSymbol) => {
    names.push(symbol.name);
    symbol.children.forEach(visit);
  };

  symbols.forEach(visit);
  return names;
}

async function renameEdits(
  uri: vscode.Uri,
  position: vscode.Position,
  newName: string,
): Promise<vscode.WorkspaceEdit | undefined> {
  return vscode.commands.executeCommand<vscode.WorkspaceEdit>(
    'vscode.executeDocumentRenameProvider',
    uri,
    position,
    newName,
  );
}

suite('Modelable LSP Smoke Tests', function () {
  this.timeout(60_000);

  let uri: vscode.Uri;

  suiteSetup(async () => {
    const ws = vscode.workspace.workspaceFolders?.[0];
    assert.ok(ws, 'No workspace folder open — check runTests launchArgs');
    uri = vscode.Uri.joinPath(ws.uri, 'ml-credit-risk.mdl');

    const doc = await vscode.workspace.openTextDocument(uri);
    await vscode.window.showTextDocument(doc);

    // Ensure the extension is active before waiting for diagnostics.
    const ext = vscode.extensions.getExtension('modelable.modelable-vscode');
    assert.ok(ext, 'Extension not installed');
    if (!ext.isActive) await ext.activate();

    // Wait for the LSP server to publish its first diagnostics for this file.
    await waitForDiagnostics(uri);
  });

  test('extension activates without error', () => {
    const ext = vscode.extensions.getExtension('modelable.modelable-vscode');
    assert.ok(ext, 'Extension not found');
    assert.ok(ext.isActive, 'Extension is not active');
  });

  test('hover returns content for a cross-domain type reference', async () => {
    // Line 19 (0-indexed), char 15: inside `lending.LoanApplication @ 1`
    const position = new vscode.Position(19, 15);
    const results = await vscode.commands.executeCommand<vscode.Hover[]>(
      'vscode.executeHoverProvider',
      uri,
      position,
    );
    assert.ok(results && results.length > 0, 'No hover result returned');
    const text = results
      .flatMap(h => h.contents)
      .map(c => (typeof c === 'string' ? c : (c as vscode.MarkdownString).value))
      .join('\n');
    assert.ok(
      text.includes('LoanApplication'),
      `Expected hover to mention LoanApplication, got:\n${text}`,
    );
  });

  test('go-to-definition resolves cross-file reference to lending.mdl', async () => {
    const position = new vscode.Position(19, 15);
    const results = await vscode.commands.executeCommand<vscode.Location[]>(
      'vscode.executeDefinitionProvider',
      uri,
      position,
    );
    assert.ok(results && results.length > 0, 'No definition result returned');
    const targetPath = results[0].uri.fsPath;
    assert.ok(
      targetPath.endsWith('lending.mdl'),
      `Expected definition in lending.mdl, got: ${targetPath}`,
    );
  });

  test('completion suggests projection fields in a body', async () => {
    const position = new vscode.Position(43, '    bureau_credit_score    <- bur.'.length);
    const labels = await completionLabels(uri, position);
    assert.ok(labels.length > 0, 'No completion results returned');
    assert.ok(
      labels.includes('bureau_credit_score'),
      `Expected bureau_credit_score in completions: ${labels.join(', ')}`,
    );
  });

  test('document symbols include the current projection fields', async () => {
    const names = await documentSymbolNames(uri);
    assert.ok(names.includes('ml-credit-risk'), `Expected ml-credit-risk in document symbols: ${names.join(', ')}`);
    assert.ok(
      names.includes('CreditFeaturesOffline'),
      `Expected CreditFeaturesOffline in document symbols: ${names.join(', ')}`,
    );
    assert.ok(
      names.includes('bureau_credit_score'),
      `Expected bureau_credit_score in document symbols: ${names.join(', ')}`,
    );
  });

  test('rename returns a workspace edit for an aliased field reference', async () => {
    const position = new vscode.Position(27, '    applicationId          <- '.length + 5);
    const edit = await renameEdits(uri, position, 'inputApplicationId');
    assert.ok(edit, 'Expected a workspace edit from rename');
    const changes = edit!.entries().find(([editUri]) => editUri.toString() === uri.toString())?.[1] ?? [];
    assert.ok(changes.length > 0, 'Expected rename edits in the current document');
    assert.ok(
      changes.some((change: vscode.TextEdit) => change.newText === 'inputApplicationId'),
      `Expected rename edits to contain inputApplicationId, got: ${changes.map((change: vscode.TextEdit) => change.newText).join(', ')}`,
    );
  });

  test('no unresolved model reference diagnostics on ml-credit-risk.mdl', () => {
    const diagnostics = vscode.languages.getDiagnostics(uri);
    const unresolved = diagnostics.filter(d =>
      d.message.includes('unresolved model reference'),
    );
    assert.strictEqual(
      unresolved.length,
      0,
      `Unexpected diagnostics: ${unresolved.map(d => d.message).join(', ')}`,
    );
  });
});
