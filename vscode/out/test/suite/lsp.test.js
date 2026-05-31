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
const fs = __importStar(require("fs/promises"));
const os = __importStar(require("os"));
const path = __importStar(require("path"));
const MESSY_TEXT = `
domain customer {
entity Customer @ 1 (additive) {
@key customerId: uuid
email?: string
}
}
`.trim();
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
async function documentSymbolNames(uri) {
    const results = await vscode.commands.executeCommand('vscode.executeDocumentSymbolProvider', uri);
    if (!results) {
        return [];
    }
    const symbols = results;
    const names = [];
    const visit = (symbol) => {
        names.push(symbol.name);
        symbol.children.forEach(visit);
    };
    symbols.forEach(visit);
    return names;
}
async function renameEdits(uri, position, newName) {
    return vscode.commands.executeCommand('vscode.executeDocumentRenameProvider', uri, position, newName);
}
async function formatEdits(uri, tabSize, insertSpaces) {
    const results = await vscode.commands.executeCommand('vscode.executeFormatDocumentProvider', uri, { tabSize, insertSpaces });
    return results ?? [];
}
async function inlayHints(uri, range) {
    const results = await vscode.commands.executeCommand('vscode.executeInlayHintProvider', uri, range);
    return results ?? [];
}
async function referenceLocations(uri, position) {
    const results = await vscode.commands.executeCommand('vscode.executeReferenceProvider', uri, position);
    return results ?? [];
}
function positionOf(text, needle) {
    const lines = text.split(/\r?\n/);
    for (let line = 0; line < lines.length; line++) {
        const character = lines[line].indexOf(needle);
        if (character >= 0) {
            return new vscode.Position(line, character);
        }
    }
    throw new Error(`Unable to find ${needle} in document text`);
}
function applyTextEdits(text, edits) {
    const lines = text.split(/\r?\n/);
    const offsets = [];
    let offset = 0;
    for (let i = 0; i < lines.length; i++) {
        offsets.push(offset);
        offset += lines[i].length + 1;
    }
    const toOffset = (position) => offsets[position.line] + position.character;
    let result = text;
    for (const edit of [...edits].sort((a, b) => toOffset(b.range.start) - toOffset(a.range.start))) {
        const start = toOffset(edit.range.start);
        const end = toOffset(edit.range.end);
        result = `${result.slice(0, start)}${edit.newText}${result.slice(end)}`;
    }
    return result;
}
async function createTempMdlDocument(text) {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'modelable-vscode-'));
    const filePath = path.join(dir, 'formatting.mdl');
    await fs.writeFile(filePath, text, 'utf8');
    return {
        uri: vscode.Uri.file(filePath),
        cleanup: async () => {
            for (let attempt = 0; attempt < 5; attempt++) {
                try {
                    await fs.rm(dir, { recursive: true, force: true });
                    return;
                }
                catch (error) {
                    if (attempt === 4) {
                        throw error;
                    }
                    await new Promise(resolve => setTimeout(resolve, 100 * (attempt + 1)));
                }
            }
        },
    };
}
suite('Modelable LSP Smoke Tests', function () {
    this.timeout(60000);
    let uri;
    let lendingUri;
    let text;
    let lendingText;
    suiteSetup(async () => {
        const ws = vscode.workspace.workspaceFolders?.[0];
        assert.ok(ws, 'No workspace folder open — check runTests launchArgs');
        uri = vscode.Uri.joinPath(ws.uri, 'ml-credit-risk.mdl');
        lendingUri = vscode.Uri.joinPath(ws.uri, 'lending.mdl');
        const doc = await vscode.workspace.openTextDocument(uri);
        text = doc.getText();
        await vscode.window.showTextDocument(doc);
        const lendingDoc = await vscode.workspace.openTextDocument(lendingUri);
        lendingText = lendingDoc.getText();
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
    test('document symbols include the current projection fields', async () => {
        const names = await documentSymbolNames(uri);
        assert.ok(names.includes('ml-credit-risk'), `Expected ml-credit-risk in document symbols: ${names.join(', ')}`);
        assert.ok(names.includes('CreditFeaturesOffline'), `Expected CreditFeaturesOffline in document symbols: ${names.join(', ')}`);
        assert.ok(names.includes('bureau_credit_score'), `Expected bureau_credit_score in document symbols: ${names.join(', ')}`);
    });
    test('rename returns a workspace edit for an aliased field reference', async () => {
        const position = new vscode.Position(27, '    applicationId          <- '.length + 5);
        const edit = await renameEdits(uri, position, 'inputApplicationId');
        assert.ok(edit, 'Expected a workspace edit from rename');
        const changes = edit.entries().find(([editUri]) => editUri.toString() === uri.toString())?.[1] ?? [];
        assert.ok(changes.length > 0, 'Expected rename edits in the current document');
        assert.ok(changes.some((change) => change.newText === 'inputApplicationId'), `Expected rename edits to contain inputApplicationId, got: ${changes.map((change) => change.newText).join(', ')}`);
    });
    test('formatting returns normalized indentation for a messy document', async () => {
        const temp = await createTempMdlDocument(MESSY_TEXT);
        try {
            const doc = await vscode.workspace.openTextDocument(temp.uri);
            await vscode.window.showTextDocument(doc);
            const edits = await formatEdits(temp.uri, 2, true);
            assert.ok(edits.length > 0, 'Expected format edits for messy document');
            assert.strictEqual(applyTextEdits(MESSY_TEXT, edits), [
                'domain customer {',
                '  entity Customer @ 1 (additive) {',
                '    @key customerId: uuid',
                '    email?: string',
                '  }',
                '}',
            ].join('\n'));
        }
        finally {
            await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
            await temp.cleanup();
        }
    });
    test('references include model declarations and usages', async () => {
        const position = positionOf(lendingText, 'LoanApplication');
        const references = await referenceLocations(lendingUri, position);
        assert.ok(references.length > 0, 'Expected references for LoanApplication');
        const declarationLine = 5;
        const usageLine = 19;
        const declarationReferences = references.filter(r => r.range.start.line === declarationLine);
        const usageReferences = references.filter(r => r.range.start.line === usageLine);
        assert.ok(declarationReferences.length > 0, `Expected a reference on the LoanApplication declaration at line ${declarationLine + 1}`);
        assert.ok(usageReferences.length > 0, `Expected a reference on the LoanApplication usage at line ${usageLine + 1}`);
        assert.ok(references.some(r => r.uri.toString() === lendingUri.toString() && r.range.start.line === declarationLine), `Expected a reference on the LoanApplication declaration, got: ${references.map(r => r.range.start.line).join(', ')}`);
        assert.ok(references.some(r => r.uri.toString() === uri.toString() && r.range.start.line === usageLine), `Expected a reference on the LoanApplication usage, got: ${references.map(r => r.range.start.line).join(', ')}`);
    });
    test('inlay hints include direct field types', async () => {
        const lines = text.split(/\r?\n/);
        const targetLine = lines.findIndex(line => line.includes('requested_amount_cents <- app.requestedAmountCents'));
        assert.ok(targetLine >= 0, 'Expected requested_amount_cents mapping in the document');
        const hints = await inlayHints(uri, new vscode.Range(new vscode.Position(0, 0), new vscode.Position(lines.length - 1, lines[lines.length - 1].length)));
        assert.ok(hints.length > 0, 'Expected inlay hints for the current document');
        const lineHints = hints.filter(h => h.position.line === targetLine);
        assert.ok(lineHints.length > 0, `Expected an inlay hint on line ${targetLine + 1}`);
        const labels = lineHints
            .map(h => (typeof h.label === 'string' ? h.label : h.label.map(part => part.value).join('')))
            .join(', ');
        assert.ok(labels.includes(': int'), `Expected a direct mapping type hint on line ${targetLine + 1}, got: ${labels}`);
    });
    test('no unresolved model reference diagnostics on ml-credit-risk.mdl', () => {
        const diagnostics = vscode.languages.getDiagnostics(uri);
        const unresolved = diagnostics.filter(d => d.message.includes('unresolved model reference'));
        assert.strictEqual(unresolved.length, 0, `Unexpected diagnostics: ${unresolved.map(d => d.message).join(', ')}`);
    });
});
