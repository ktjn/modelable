# 1. RAG Context Selection Design

## Scope

Add the first deterministic context-selection policy for Modelable's RAG
generation pipeline. It removes duplicate evidence, limits repeated chunks
from one source document, preserves retrieval rank within the selected set,
and applies the existing whole-chunk word budget before answer generation.

This slice does not add reranking, score thresholds, near-duplicate hashing,
or remote adjacent-chunk fetching. The current Searchable Python client can
return stored chunks but has no API to enumerate neighboring chunks by
`source_path` and `chunk_index`; adjacency expansion is a separate follow-up.

## Policy

`select_context(chunks, max_context_words, max_chunks_per_source=None)`:

1. Reject non-positive budgets and source caps.
2. Walk retrieved chunks in score/rank order.
3. Skip repeated `external_id` values and repeated non-empty `content_hash`
   values.
4. Skip chunks after a source document reaches its optional cap.
5. Admit only complete chunks that fit the remaining word budget.
6. Return the selected chunks in their original order.

If a duplicate is skipped, its citation is not emitted. The original
`RetrievedChunk.score` remains unchanged. A source cap of `None` preserves the
current behavior; the first generation integration uses a conservative default
of two chunks per source.

## Integration

`answer_with_retrieval` retrieves its candidate set, passes it through
`select_context`, builds the evidence prompt from the selected chunks, and
creates citations only for selected chunks. Existing insufficient-evidence and
provider behavior remains unchanged.

## ADR applicability

No ADR is needed. This adds a deterministic consumer-side policy without
changing storage, deployment, security, or embedding-model ownership.
