# 1. Documentation Retriever Design

## Scope

Add the Phase 5 retrieval abstraction from the full Modelable RAG plan. This
slice searches an existing Searchable JSON index and returns Modelable-owned
`RetrievedChunk` values. It does not add prompts, LLM calls, embeddings,
hybrid search, reranking, or context budgeting.

## ADR applicability

No ADR is needed for this incremental adapter: it follows the already approved
Searchable integration and introduces no new deployment, security, or storage
architecture.

## API

`modelable.rag.retriever` will expose:

```python
@dataclass(slots=True, frozen=True)
class RetrievedChunk:
    id: int
    external_id: str
    url: str
    score: float
    title: str
    heading: str | None
    content: str
    source_path: str
    heading_path: list[str]
    content_hash: str | None


class DocumentationRetriever:
    def __init__(self, index_url: str | Path) -> None: ...

    def search(self, query: str, *, limit: int = 8) -> list[RetrievedChunk]: ...
```

The implementation constructs `searchable_client.SearchClient` once and maps
its ordered hits to the Modelable dataclass. Searchable numeric IDs remain
internal; external IDs and URLs are preserved for later citations.

## Validation and mapping

Reject blank queries and non-positive limits with `ValueError`. Read `title`,
`heading`, `content`, and `source_path` from stored fields. Read
`headingPath` from JSON metadata, defaulting to an empty list only when absent.
Missing required stored fields or malformed metadata are errors rather than
silently incomplete results.

## Testing

Use a small fake Searchable client for deterministic unit tests covering query
options, ordering, field/metadata mapping, and validation. Add an integration
test that builds an index with the existing writer and searches it through the
real client.
