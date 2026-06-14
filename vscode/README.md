# Modelable VS Code Extension

This folder contains a minimal VS Code extension that launches the repo-local Modelable language server over stdio.

## Setup

1. Make sure the CLI environment is ready:
   ```powershell
   cd ..\cli
   uv sync --extra dev
   ```
2. Install the extension dependencies:
   ```powershell
   cd ..\vscode
   npm ci
   ```

## Run

Open the `vscode/` folder in VS Code and press `F5` to start the Extension Development Host.

The extension registers `*.mdl` files as `mdl` documents and resolves the language server command in this order:

1. The `modelable.serverCommand` setting — an explicit `[command, ...args]` override.
2. The `modelable.pythonPath` setting — launched as `<pythonPath> -m modelable.lsp`.
3. The repo-local interpreter at `cli/.venv/Scripts/python.exe` (or `cli/.venv/bin/python` on macOS/Linux) — used automatically inside this checkout.
4. `modelable lsp` resolved from `PATH`.

Open a `.mdl` file in the development host to test diagnostics, completion, hover, definition, references, symbols, formatting, rename, and code actions.

## Packaging for use in another project

Build an installable `.vsix`:

```powershell
npm ci
npm run package
```

This produces `modelable-vscode-<version>.vsix`. Install it into another VS Code instance with:

```powershell
code --install-extension modelable-vscode-0.5.0.vsix
```

Outside this repo there is no `cli/.venv` to auto-detect, so the host project needs `modelable` available — either install the CLI into the project's environment (see [getting started](../docs/getting-started.md)) so `modelable lsp` resolves from `PATH`, or point the extension at a specific interpreter/command via the `modelable.pythonPath` or `modelable.serverCommand` settings.

## Smoke tests

Run the extension smoke suite from this folder:

```powershell
npm ci
npm run build
npm test
```

CI runs the same suite on Ubuntu under `xvfb-run -a npm test`.
On Windows, close any running desktop VS Code windows before `npm test`; the smoke runner now fails fast if the desktop app holds the update mutex.
