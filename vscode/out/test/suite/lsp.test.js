"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
const vscode = __importStar(require("vscode"));
const assert = __importStar(require("assert"));
function waitForDiagnostics(uri, timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`Timeout (${timeoutMs}ms) waiting for diagnostics on ${uri.fsPath}`)), timeoutMs);
        const sub = vscode.languages.onDidChangeDiagnostics(e => {
            if (e.uris.some(u => u.toString() === uri.toString())) {
                clearTimeout(timer);
                sub.dispose();
                resolve(vscode.languages.getDiagnostics(uri));
            }
        });
    });
}
async function completionLabels(uri, position) {
    const results = await vscode.commands.executeCommand('vscode.executeCompletionItemProvider', uri, position);
    if (!results) {
        return [];
    }
    const items = Array.isArray(results) ? results : results.items;
    return items.map(item => item.label.toString());
}
suite('Modelable LSP Smoke Tests', function () {
    this.timeout(60000);
    let uri;
    suiteSetup(async () => {
        const ws = vscode.workspace.workspaceFolders?.[0];
        assert.ok(ws, 'No workspace folder open — check runTests launchArgs');
        uri = vscode.Uri.joinPath(ws.uri, 'ml-credit-risk.mdl');
        const doc = await vscode.workspace.openTextDocument(uri);
        await vscode.window.showTextDocument(doc);
        // Ensure the extension is active before waiting for diagnostics.
        const ext = vscode.extensions.getExtension('modelable.modelable-vscode');
        assert.ok(ext, 'Extension not installed');
        if (!ext.isActive)
            await ext.activate();
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
        const results = await vscode.commands.executeCommand('vscode.executeHoverProvider', uri, position);
        assert.ok(results && results.length > 0, 'No hover result returned');
        const text = results
            .flatMap(h => h.contents)
            .map(c => (typeof c === 'string' ? c : c.value))
            .join('\n');
        assert.ok(text.includes('LoanApplication'), `Expected hover to mention LoanApplication, got:\n${text}`);
    });
    test('go-to-definition resolves cross-file reference to lending.mdl', async () => {
        const position = new vscode.Position(19, 15);
        const results = await vscode.commands.executeCommand('vscode.executeDefinitionProvider', uri, position);
        assert.ok(results && results.length > 0, 'No definition result returned');
        const targetPath = results[0].uri.fsPath;
        assert.ok(targetPath.endsWith('lending.mdl'), `Expected definition in lending.mdl, got: ${targetPath}`);
    });
    test('completion suggests projection fields in a body', async () => {
        const position = new vscode.Position(43, '    bureau_credit_score    <- bur.'.length);
        const labels = await completionLabels(uri, position);
        assert.ok(labels.length > 0, 'No completion results returned');
        assert.ok(labels.includes('bureau_credit_score'), `Expected bureau_credit_score in completions: ${labels.join(', ')}`);
    });
    test('no unresolved model reference diagnostics on ml-credit-risk.mdl', () => {
        const diagnostics = vscode.languages.getDiagnostics(uri);
        const unresolved = diagnostics.filter(d => d.message.includes('unresolved model reference'));
        assert.strictEqual(unresolved.length, 0, `Unexpected diagnostics: ${unresolved.map(d => d.message).join(', ')}`);
    });
});
