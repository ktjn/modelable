# 2026-08-01 Modelable Playground RAG Adapter Design

## Goal

Add explicit documentation retrieval to the static web playground so `/docs <question>` uses the same Python RAG semantics as CLI and LSP while ordinary chat and model-editing flows remain unchanged.

## Decisions

- The playground ships one repository-built documentation index as static, same-origin assets under `web/public/docs-index/`.
- The index uses Searchable's released JSON shard formats for the first Playground integration; the manifest remains the normal Searchable JSON manifest required to address hashed shards.
- Pyodide loads `searchable-client` and the browser-safe Modelable RAG adapter. TypeScript does not reimplement Searchable parsing or ranking.
- The browser protocol receives the index URL as a validated, build-time configuration value. It accepts only a same-origin URL under the playground asset root and never accepts arbitrary user paths or remote origins.
- `/docs` is the only automatic retrieval trigger. A normal message continues through the existing workspace conversation planner, and `/docs` without a bundled index returns a recoverable explanatory answer.
- Retrieved answers preserve source URL, title, heading, and score as citations. The provider receives bounded retrieved evidence through the existing pending-LLM protocol.
- The index is immutable for a browser session and is loaded lazily on the first `/docs` request. Retrieval failures do not terminate the compiler worker or invalidate workspace state.

## Architecture

The build assembles the browser assets in three steps: generate the Markdown documentation index with `modelable docs-index`, keep the released JSON shard formats so structured citation metadata survives, and copy the output into the static playground distribution. The runtime passes the configured manifest URL into `BrowserConversationService`; its browser backend creates one `DocumentationRetriever` per session and handles explicit `/docs` messages before ordinary planning.

The Python browser wheel includes only the retrieval modules and their pure-Python Searchable client dependencies. The browser adapter uses a same-origin URL and the existing Searchable fetch/cache implementation, so JSON shard loading works under Pyodide without a second TypeScript index implementation. The TypeScript client exposes the configuration but remains responsible only for URL construction, request serialization, and citation presentation.

## Error handling and safety

- Reject malformed or cross-origin index URLs before the worker reaches Searchable.
- Reject manifests whose shard references escape the configured asset directory after URL resolution.
- Treat missing, malformed, or unavailable indexes as a user-visible `/docs` answer; do not crash the worker.
- Bound retrieved chunks and evidence words using the same limits as the shared documentation answer adapter.
- Render citation labels as text and links with safe URL handling; do not inject provider or retrieved HTML.
- Do not persist documentation index bytes, provider secrets, or retrieved answers in IndexedDB.

## Testing and acceptance

- Python browser tests cover Searchable retrieval, lazy session binding, explicit `/docs`, missing-index recovery, URL containment, and ordinary-turn parity.
- TypeScript tests cover index URL configuration, request shape, citation rendering, and no-index UX.
- The browser build validates that the generated asset set contains one manifest plus JSON shard files and that the Pyodide wheel includes the required pure-Python dependencies.
- Existing CLI, LSP, browser compiler, and playground gates remain green.

## ADR impact

No new ADR is required. The static same-origin playground, Pyodide worker boundary, shared Python semantics, and optional local AI provider are already accepted architecture decisions; this slice only exposes the existing RAG contract through that boundary. Structured binary document-store support remains a follow-up in the Searchable repository; the Playground stays JSON until that release is available.

## Non-goals

- Automatic RAG for ordinary chat messages.
- Vector embeddings or a built-in browser embedding provider.
- User-uploaded or arbitrary remote Searchable indexes.
- Changes to workspace persistence, compiler semantics, or mutation/apply lifecycle.
