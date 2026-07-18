# Modelable Playground Design

## Goal

Provide a fully static browser-based playground for Modelable with no backend services.

## Architecture

- Static hosting (GitHub Pages)
- React + Monaco Editor
- Web Worker hosting Pyodide
- Web Worker hosting WebLLM
- Browser File System API for open/save
- IndexedDB for caching models and compiler assets

## Components

### UI
- Monaco editor for `.mdl`
- Diagnostics panel
- Generated artifact panel
- Lineage graph
- Compatibility report
- Model selection
- LLM settings

### Compiler Worker
Runs CPython (Pyodide) and `modelable-core`.

Responsibilities:
- Parse
- Validate
- Compile
- Format
- Compatibility analysis
- Lineage

### LLM Worker
Runs WebLLM using WebGPU.

Responsibilities:
- Model download
- Prompt execution
- Progress reporting
- Streaming responses

## Communication

UI -> Compiler Worker: validate, compile, format, lineage, diff.

Compiler Worker emits LLM requests to the LLM Worker, which performs inference and returns structured responses.

## Packaging

Split into:

- modelable-core
- modelable-cli
- modelable-lsp
- web

Only modelable-core is loaded into Pyodide.

## Supported Features

- Validation
- Compilation
- Code generation
- AI-assisted model generation
- AI-assisted updates
- Import/export
- Offline mode

## Unsupported

- PostgreSQL
- LSP server
- Remote synchronization
- Runtime services

## Deployment

GitHub Pages only.

Assets:
- React bundle
- Pyodide runtime
- modelable-core wheel
- WebLLM runtime
- Quantized model

No backend infrastructure required.

## Future

- Multi-file workspace
- Collaborative editing
- PWA
- Offline-first
- GitHub integration