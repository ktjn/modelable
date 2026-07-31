from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from searchable_client import SearchClient  # type: ignore[import-untyped]
from searchable_client.search import SearchOptions  # type: ignore[import-untyped]


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


class _SearchClient(Protocol):
    def search(self, query: str, options: SearchOptions) -> Any: ...


class DocumentationRetriever:
    def __init__(self, index_url: str | Path, *, client: _SearchClient | None = None) -> None:
        self._client = client if client is not None else SearchClient(str(index_url))

    def search(self, query: str, *, limit: int = 8) -> list[RetrievedChunk]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be blank")
        if limit <= 0:
            raise ValueError("limit must be positive")

        result = self._client.search(
            normalized_query,
            SearchOptions(limit=limit),
        )
        return [self._map_hit(hit) for hit in result.hits]

    @staticmethod
    def _map_hit(hit: Any) -> RetrievedChunk:
        fields = hit.fields
        required_fields = ("title", "heading", "content", "source_path")
        for field in required_fields:
            if field not in fields:
                raise ValueError(f"missing stored field: {field}")

        if hit.external_id is None:
            raise ValueError("missing hit external_id")

        metadata = hit.metadata
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("hit metadata must be a JSON object")

        heading_path = metadata.get("headingPath", [])
        if not isinstance(heading_path, list) or not all(isinstance(item, str) for item in heading_path):
            raise ValueError("hit metadata headingPath must be a list of strings")

        return RetrievedChunk(
            id=hit.id,
            external_id=hit.external_id,
            url=hit.url,
            score=hit.score,
            title=fields["title"],
            heading=fields["heading"] or None,
            content=fields["content"],
            source_path=fields["source_path"],
            heading_path=list(heading_path),
            content_hash=hit.content_hash,
        )
