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
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
const os = __importStar(require("os"));
const test_electron_1 = require("@vscode/test-electron");
// Pass MODELABLE_VSCODE_HEADLESS=1 to run with --headless --disable-gpu, which is
// useful for local runs without a display server. CI already provides a virtual
// display via xvfb-run, where --headless is not a recognized option and breaks
// extension host activation, so it is opt-in rather than the default.
const headless = process.env['MODELABLE_VSCODE_HEADLESS'] === '1';
async function main() {
    // __dirname compiles to vscode/out/test/
    const extensionDevelopmentPath = path.resolve(__dirname, '../..');
    const extensionTestsPath = path.resolve(__dirname, './suite/index');
    const workspaceFolder = path.resolve(__dirname, '../../../samples/scenarios/04-credit-risk-feature-store');
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'modelable-vscode-'));
    const settingsDir = path.join(userDataDir, 'User');
    fs.mkdirSync(settingsDir, { recursive: true });
    fs.writeFileSync(path.join(settingsDir, 'settings.json'), JSON.stringify({ 'update.mode': 'none' }, null, 2));
    const extraArgs = headless ? ['--headless', '--disable-gpu'] : [];
    await (0, test_electron_1.runTests)({
        extensionDevelopmentPath,
        extensionTestsPath,
        launchArgs: [...extraArgs, '--user-data-dir', userDataDir, workspaceFolder],
    });
}
main().catch(err => {
    console.error('Failed to run VS Code tests:', err);
    process.exit(1);
});
