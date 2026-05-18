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
   npm install
   ```

## Run

Open the `vscode/` folder in VS Code and press `F5` to start the Extension Development Host.

The extension registers `*.mdl` files as `mdl` documents and starts:

```powershell
C:\git\modelable\cli\.venv\Scripts\python.exe -m modelable.lsp
```

Open a `.mdl` file in the development host to test diagnostics, completion, hover, definition, references, symbols, formatting, rename, and code actions.
