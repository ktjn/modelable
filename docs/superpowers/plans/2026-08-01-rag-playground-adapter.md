# Modelable Playground RAG Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable explicit `/docs <question>` documentation answers in the static Playground using the shared Python RAG pipeline and one same-origin binary Searchable index.

**Architecture:** Extend the browser-only Python wheel with a small browser RAG adapter and pure-Python Searchable client dependencies. Pass a validated same-origin index manifest URL into the Pyodide conversation service, bind one lazy retriever per browser session, and route only `/docs` through the existing `documentation_chat_reply` path. Generate the binary index during the existing browser asset preparation and render the resulting source citations through the existing assistant answer UI.

**Tech Stack:** Python 3.14, Pyodide 314.0.2, `searchable-client` 0.2.0, `searchable-analysis` 0.1.0, `searchable-indexer` 0.1.1, TypeScript, React, Vite, Vitest, Playwright.

## Global Constraints

- Keep ordinary conversation and mutation behavior unchanged; only explicit `/docs` invokes retrieval.
- Use one static binary Searchable index; do not add a TypeScript index parser or an arbitrary remote/user-supplied index option.
- Accept only same-origin index URLs under the playground asset root and validate all manifest shard references before searching.
- Do not persist index bytes, provider secrets, or retrieved answers in IndexedDB.
- Run the Modelable `cli/` gates before each commit: `uv run ruff format .`, `uv run ruff check .`, mypy baseline ratchet, and `uv run pytest --tb=short`.
- Run `cd web && npm run check && npm test` for TypeScript changes and the full browser playground gate before publication.

---

### Task 1: Add the browser Searchable dependency closure and retrieval adapter

**Files:**
- Modify: `cli/browser/pyproject.toml`
- Modify: `cli/browser/browser-lock.json`
- Modify: `cli/scripts/build_browser_wheel.py`
- Create: `cli/src/modelable/browser/rag.py`
- Test: `cli/tests/test_browser_packaging.py`
- Test: `cli/tests/test_browser_rag.py`

**Interfaces:**
- Consumes: Searchable `SearchClient` and the shared `RetrievedChunk`/`DocumentationRetriever` mapping contract.
- Produces: `BrowserDocumentationRetriever(index_url: str, asset_root: str)`, with `search(query: str, limit: int = 8) -> list[RetrievedChunk]` and `validate_index_url(index_url: str, asset_root: str) -> str`.

- [ ] **Step 1: Write failing adapter and packaging tests**

Add tests for a same-origin manifest URL, a cross-origin URL, a `..` shard reference, and a binary term/document index queried through a fake `SearchClient`. Assert that the browser wheel source selection includes `modelable/browser/rag.py` and does not import desktop-only modules.

- [ ] **Step 2: Run focused tests and verify failure**

Run `uv run pytest tests/test_browser_rag.py tests/test_browser_packaging.py -q` from `cli/`. Expect failures because the adapter and dependency closure do not yet exist.

- [ ] **Step 3: Implement the minimal browser adapter**

Use `urllib.parse.urljoin` and `urlparse` to enforce same-origin asset-root containment, validate the manifest through Searchable, and construct `DocumentationRetriever` with the browser-safe client. Keep the adapter lexical-only and translate malformed/unavailable index failures into a small browser retrieval exception.

- [ ] **Step 4: Add the pure-Python browser dependency closure**

Add pinned `searchable-client==0.2.0` and its `searchable-analysis==0.1.0` dependency to the browser package and record their exact wheel URLs, hashes, and versions in `browser-lock.json`. Extend the wheel builder’s selected source and forbidden-import checks only as needed for the adapter.

- [ ] **Step 5: Run focused tests and commit**

Run `uv run pytest tests/test_browser_rag.py tests/test_browser_packaging.py -q`, then the four required `cli/` gates. Commit with `feat(browser): add Pyodide documentation retrieval`.

### Task 2: Bind the static index to browser conversation sessions

**Files:**
- Modify: `cli/src/modelable/browser/conversation.py`
- Modify: `cli/src/modelable/browser/dispatch.py`
- Modify: `cli/src/modelable/browser/__init__.py`
- Test: `cli/tests/test_browser_conversation.py`
- Test: `cli/tests/test_browser_api.py`

**Interfaces:**
- Consumes: `BrowserDocumentationRetriever` from Task 1 and `documentation_chat_reply` from `modelable.llm.chat`.
- Produces: `BrowserConversationService(..., documentation_index_url: str | None = None, documentation_asset_root: str | None = None)` and explicit `/docs` answers with the existing `ConversationReply` shape.

- [ ] **Step 1: Write failing session and dispatch tests**

Cover lazy retriever creation only on the first `/docs`, retriever reuse for later `/docs`, ordinary-turn parity, missing-index recovery, and exact dispatch payload validation for the configured index URL.

- [ ] **Step 2: Run focused tests and verify failure**

Run `uv run pytest tests/test_browser_conversation.py tests/test_browser_api.py -k docs -q` from `cli/`. Expect failures because browser sessions currently have no documentation retriever or index configuration.

- [ ] **Step 3: Implement session-bound `/docs` routing**

Store the optional index configuration on the service, instantiate the browser retriever lazily per session, and route `/docs` through `documentation_chat_reply`. Preserve the existing provider handoff and failure cleanup. A missing or invalid index must become an answer text, not a terminal browser error.

- [ ] **Step 4: Validate worker configuration**

Add an exact `documentationIndexUrl` initialization/configuration field to the browser dispatch path. Reject non-string values and cross-origin/out-of-root URLs before constructing the service. Do not accept the URL on each turn.

- [ ] **Step 5: Run focused tests and commit**

Run the focused browser tests plus `uv run pytest tests/test_browser_conversation.py tests/test_browser_api.py -q`, then the four required `cli/` gates. Commit with `feat(browser): route playground docs questions through RAG`.

### Task 3: Generate and publish one binary documentation index

**Files:**
- Modify: `cli/src/modelable/rag/index.py`
- Modify: `cli/src/modelable/commands/docs_index.py`
- Modify: `web/package.json`
- Create: `web/scripts/build-docs-index.mjs`
- Modify: `web/scripts/vendor-python-assets.mjs`
- Test: `cli/tests/test_cli_docs_index.py`
- Test: `web/src/assets.test.ts`

**Interfaces:**
- Consumes: repository Markdown documentation and the existing `modelable docs-index` command.
- Produces: `web/public/docs-index/manifest.json` plus hashed binary Searchable shards during `npm run prepare:python`, with no checked-in generated index files.

- [ ] **Step 1: Write failing index-format and asset tests**

Assert that the documentation-index build invokes the existing indexer with binary term and document formats, that the manifest references `.bin` shards, and that asset preparation rejects a missing manifest or a non-binary shard set.

- [ ] **Step 2: Run focused tests and verify failure**

Run `uv run pytest tests/test_cli_docs_index.py -q` and `cd web; npm test -- src/assets.test.ts`. Expect the new binary-format assertions to fail against the current JSON output and asset pipeline.

- [ ] **Step 3: Implement binary index output**

Add explicit binary-format parameters to the index builder/CLI while retaining compatibility for existing callers that need JSON document stores. The Playground build command must pass `term_shard_format="binary"`, `doc_store_format="binary"`, and `fuzzy_shard_format="binary"`, then use `--base-url https://ktjn.github.io/modelable/` for stable citations.

- [ ] **Step 4: Integrate the build into browser preparation**

Run the new Node script from `prepare:python` after Python assets are prepared. Stage output in `web/public/docs-index`, remove stale generated files before rebuilding, and validate that all manifest-referenced files remain below that directory.

- [ ] **Step 5: Run build and commit**

Run `cd web; npm run prepare:python`, the focused tests, `npm run check`, and the full browser playground gate. Commit with `build(web): publish binary documentation index`.

### Task 4: Expose the index through the TypeScript client and render cited answers

**Files:**
- Modify: `web/src/client.ts`
- Modify: `web/src/compiler.worker.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/ai/chat-types.ts`
- Modify: `web/src/ai/ChatPanel.tsx`
- Test: `web/src/client.test.ts`
- Test: `web/src/App.test.tsx`
- Test: `web/src/ai/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: browser worker configuration from Task 2 and the existing `BrowserConversationReply` text containing `Sources:` labels.
- Produces: a same-origin `documentationIndexUrl` passed during worker initialization and a dedicated documentation-answer message presentation with safe citation links.

- [ ] **Step 1: Write failing TypeScript tests**

Assert that the client initialization includes the expected `/modelable/playground/docs-index/manifest.json` URL, ordinary conversation payloads do not change, `/docs` replies are represented as documentation answers, and citation links are rendered as text-safe anchors.

- [ ] **Step 2: Run focused tests and verify failure**

Run `cd web; npm test -- src/client.test.ts src/App.test.tsx src/ai/ChatPanel.test.tsx`. Expect failures because initialization has no documentation configuration and all answers use the generic explanation message.

- [ ] **Step 3: Implement configuration and message typing**

Derive the manifest URL from `import.meta.env.BASE_URL` or the existing static asset base, send it once in the worker initialization payload, and add a `kind: 'docs'` assistant message that stores the answer and parsed citation records without changing provider completion requests.

- [ ] **Step 4: Implement safe citation rendering**

Parse only the shared `Sources:` lines into `{ label, externalId, url }`, preserve the answer body as Markdown, and render URL text/links with normal React attributes. Invalid URLs remain visible text and never become injected HTML.

- [ ] **Step 5: Run focused tests and commit**

Run `cd web; npm run check; npm test`, then the complete browser playground gate. Commit with `feat(web): show cited playground documentation answers`.

### Task 5: Documentation, closeout, and cross-surface verification

**Files:**
- Modify: `docs/cli-reference.md`
- Modify: `docs/playground-design.md`
- Modify: `ROADMAP.md`
- Modify: `docs/superpowers/plans/2026-08-01-rag-playground-adapter.md`
- Test: `cli/tests/test_release_workflow.py` if asset/build routing changes require it

- [ ] **Step 1: Document the browser contract**

Document the bundled binary index, explicit `/docs` trigger, same-origin restriction, citation behavior, and the fact that ordinary browser chat remains non-RAG.

- [ ] **Step 2: Reconcile roadmap status**

Mark the Playground RAG client slice as shipped only after the browser build and acceptance tests pass; retain vector/browser embedding and user-provided indexes as deferred work.

- [ ] **Step 3: Run final validation**

Run the four `cli/` gates, `cd web; npm run check; npm test; npm run build; npm run check:budgets`, and `uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict`. Review generated docs and asset manifests.

- [ ] **Step 4: Commit closeout and prepare publication**

Run `git diff --check`, inspect `git diff --stat main...HEAD`, and commit the documentation/roadmap closeout. Move `docs/superpowers/specs/2026-08-01-rag-playground-adapter-design.md` to `docs/superpowers/specs/archived/` and `docs/superpowers/plans/2026-08-01-rag-playground-adapter.md` to `docs/superpowers/plans/archived/` in the same closeout PR after all implementation tasks pass.

## Completion Evidence

- `modelable docs-index` can produce a binary Searchable index consumed by the browser wheel.
- The Playground answers `/docs` locally with bounded evidence and citations.
- Ordinary chat, mutations, workspace persistence, and compiler behavior are unchanged.
- All CLI, browser, docs, and CI gates pass.
