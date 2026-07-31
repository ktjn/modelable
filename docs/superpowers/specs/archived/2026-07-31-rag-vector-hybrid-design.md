# 1. RAG Vector and Hybrid Retrieval Design

## Scope

Integrate Modelable's documentation retriever with the published Searchable
v1.0.5 Python client (`searchable-client` 0.2.0). Add explicit lexical,
vector, and hybrid retrieval modes and compare them using the existing
evaluation corpus. This phase does not add an embedding model to Modelable's
core; callers inject `embed_query(text) -> list[float]` and, optionally, the
provider descriptor required for compatibility validation.

## Ownership and dependency contract

Searchable owns vector-shard parsing, dequantization, cosine ranking,
best-passage collapse, provider/dimension validation, and hybrid Reciprocal
Rank Fusion. Modelable owns documentation-specific configuration, retrieval
mode orchestration, stable `RetrievedChunk` mapping, evaluation, and CLI/user
documentation.

The Modelable dependency floor becomes `searchable-client>=0.2.0` and
`searchable-indexer>=0.1.1`. Modelable passes the injected callable to
`SearchClient` as:

```python
SearchClient(
    index_url,
    embed_query={"embed": embed_query, "provider": provider_descriptor},
)
```

Search requests use `SearchOptions(mode="lexical" | "vector" | "hybrid", limit=...)`.
Modelable must not silently downgrade an explicitly requested vector or hybrid
mode to lexical search.

## Modelable API

`DocumentationRetriever` accepts optional embedding configuration:

```python
DocumentationRetriever(
    index_url,
    *,
    client=None,
    embed_query=None,
    embedding_provider=None,
)
```

Its `search` method accepts `mode="lexical"` by default and forwards the
selected mode and limit to Searchable. The default remains lexical so existing
callers and indexes continue to work unchanged. Vector and hybrid modes fail
with the Searchable-defined configuration errors when no embedder, vector
shard, compatible provider, or matching dimension is available.

## Evaluation

The existing deterministic evaluation metrics remain unchanged. Evaluation
adds a mode-aware entry point that runs the same cases against lexical, vector,
and hybrid retrieval and returns a stable mapping of mode name to
`EvaluationReport`. The CLI renders each mode separately and JSON output keeps
the mode names as keys. No mode is selected as the default until the measured
corpus results are reviewed.

## Embedding provider policy

The Python Searchable client remains dependency-light. Modelable does not add
Transformers or Hugging Face dependencies in this phase. A future optional
Modelable integration may provide a local Transformers adapter, but it is not
required for the retriever or evaluation APIs.

## Failure and compatibility behavior

- Lexical search works without an embedder and against existing lexical indexes.
- Vector/hybrid search requires an injected callable and a vector-enabled index.
- Searchable provider and dimension errors propagate through the Modelable
  retriever as actionable `ValueError`-compatible failures.
- Numeric Searchable IDs remain internal; `RetrievedChunk` continues exposing
  external IDs, URLs, stored content, scores, and metadata.
- Existing `docs-ask` behavior remains lexical unless its caller constructs an
  embedding-aware retriever; adding a CLI serialization format for Python
  callables is out of scope.

## ADR applicability

No new ADR is needed. This phase consumes the already-published Searchable
vector contract and adds no new storage, deployment, or embedding-model
ownership decision inside Modelable.
