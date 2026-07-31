# 1. RAG Generation Design

## Scope

Add the first Modelable RAG generation pipeline. It retrieves lexical
documentation chunks, formats complete evidence blocks, calls an existing
`LLMProvider`, and returns an answer with source citations. It does not add
embeddings, hybrid retrieval, reranking, or browser integration.

## Pipeline

`answer_with_retrieval` will:

1. Validate the question, result limit, and context budget.
2. Retrieve up to the requested number of chunks.
3. Select whole chunks in rank order until the word budget is reached; a chunk
   that does not fit is skipped rather than silently truncated.
4. Build an evidence-only prompt with stable labels `[S1]`, `[S2]`, and so on.
5. Call the existing `LLMProvider.complete(LLMRequest(...))`.
6. Return the cleaned answer and structured citations separately.

If retrieval returns no chunks, return an insufficient-evidence answer without
calling the provider. Code always appends a source list to the user-facing
answer using external IDs and URLs, never numeric Searchable IDs.

## CLI

Add `modelable docs-ask INDEX QUESTION` with `--limit`,
`--max-context-words`, `--provider`, `--model`, `--base-url`, and `--json`.
Provider construction follows the existing LLM configuration/provider
conventions. A configured provider is required unless retrieval is empty and
the command can return the insufficient-evidence response directly.

## ADR applicability

No ADR is needed: this composes the existing retriever and LLM provider
interfaces without changing deployment, storage, or security architecture.
