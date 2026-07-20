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

## Conversational workspace management

The extension contributes a native `@modelable` participant to VS Code Chat.
It can answer grounded questions and preview the same typed workspace changes
and local compilations as `modelable chat`:

```text
@modelable is the workspace valid?
@modelable add a customer entity with address
@modelable add a projection for active customers
@modelable compile this workspace to Rust
```

Read-only validation, ownership, lineage, dependency, index, compatibility,
model, and projection questions work without a model provider. Creating or
updating definitions requires the provider configured for the workspace or
CLI environment; the extension adds no separate provider setting.

Modelable selects the workspace containing the active `.mdl` editor. If there
is no active model editor, exactly one open folder containing `workspace.mdl`
must be available. Multiple candidates are ambiguous, and the participant asks
you to open a model file instead of guessing. Save all dirty `.mdl` documents
under the selected root before planning, applying, or discarding a change.

Mutation requests return a textual preview with assumptions, changed and
affected definitions, compatibility and validation findings, and a unified
diff. **View Diff** opens the exact captured before/after snapshots in VS
Code's diff editor; it does not reread or infer source.

Local compilation accepts natural-language requests through the configured
provider or the deterministic command:

```text
@modelable /compile <target> [--domain <name> ...] [--out <relative-path>] [--descriptor-set]
```

The Python service stages the real compile without changing the workspace.
Replies list affected domains and definitions, created/changed/unchanged files,
registry-ID additions, full text diffs, and binary byte sizes and SHA-256
hashes. **View generated diffs** opens exact staged text snapshots and supports
choosing among multiple outputs. Protobuf and gRPC alone accept
`--descriptor-set`; outputs must remain inside the workspace. Text previews
above 2 MiB fail with guidance to use direct `modelable compile`.

Use the native **Apply change set** or **Apply compilation** follow-up as
appropriate, or `/apply`, to act on the exact pending action ID. Only a literal
case-sensitive `/apply` or the native action authorizes a compilation; natural
language aliases authorize source changes only. **Discard** and `/discard`
remove staging. Compilation apply also checks every dirty file-scheme document
in the workspace and refuses only when one matches a generated destination;
save or close that file first.

A stale preview, changed source or destination, expired session, or restarted
language server is rejected without writing; repeat the request to create a
fresh preview. Successful compilation applies promote the exact staged bytes
with rollback protection and link to the privacy-preserving audit under
`.modelable/audit/compilations/`. Use `/reset` to close the current session and
clear its preview documents and staging. Idle server sessions expire after 30
minutes.

Registry synchronization, publishing, external-service actions, WebLLM, and a
VS Code Language Model API adapter are not implemented by this participant.

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
