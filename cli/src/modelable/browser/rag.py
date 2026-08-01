from __future__ import annotations

import re
from typing import Any, Literal, Protocol
from urllib.parse import ParseResult, urljoin, urlparse, urlunparse

from searchable_client import SearchClient  # type: ignore[import-untyped]
from searchable_client.search import SearchOptions  # type: ignore[import-untyped]

from modelable.rag.retriever import RetrievedChunk

SearchMode = Literal["lexical"]


class BrowserRetrievalError(RuntimeError):
    """Raised when browser documentation retrieval cannot complete."""


class _SearchClient(Protocol):
    def search(self, query: str, options: SearchOptions) -> Any: ...


def validate_index_url(index_url: str, asset_root: str) -> str:
    if not index_url.strip():
        raise ValueError("index_url must not be blank")
    if not asset_root.strip():
        raise ValueError("asset_root must not be blank")

    parsed_root = urlparse(asset_root)
    if not parsed_root.scheme or not parsed_root.netloc:
        raise ValueError("asset_root must be an absolute URL")

    normalized_root = _as_directory_url(parsed_root)
    resolved = urljoin(urlunparse(normalized_root), index_url)
    parsed_index = urlparse(resolved)

    if (parsed_index.scheme, parsed_index.netloc) != (normalized_root.scheme, normalized_root.netloc):
        raise ValueError("index_url must stay on the same origin as asset_root")

    if not parsed_index.path.startswith(normalized_root.path):
        raise ValueError("index_url must stay within the asset root")

    return resolved


class BrowserDocumentationRetriever:
    def __init__(self, index_url: str, asset_root: str) -> None:
        validated_index_url = validate_index_url(index_url, asset_root)
        try:
            self._client: _SearchClient = SearchClient(
                validated_index_url,
                strict=True,
                allow_cross_origin_shards=False,
            )
        except Exception as error:
            raise BrowserRetrievalError(f"could not load browser documentation index: {error}") from error

    def search(self, query: str, limit: int = 8) -> list[RetrievedChunk]:
        normalized_query = re.sub(r"[^\w\s-]", " ", query, flags=re.UNICODE)
        normalized_query = " ".join(normalized_query.split())
        if not normalized_query:
            raise ValueError("query must not be blank")
        if limit <= 0:
            raise ValueError("limit must be positive")

        try:
            result = self._client.search(
                normalized_query,
                SearchOptions(limit=limit, mode="lexical"),
            )
            return [self._map_hit(hit) for hit in result.hits]
        except Exception as error:
            raise BrowserRetrievalError(f"browser documentation retrieval failed: {error}") from error

    @staticmethod
    def _map_hit(hit: Any) -> RetrievedChunk:
        fields = hit.fields
        required_fields = ("title", "heading", "content", "source_path")
        for field in required_fields:
            if field not in fields:
                raise BrowserRetrievalError(f"missing stored field: {field}")

        if hit.external_id is None:
            raise BrowserRetrievalError("missing hit external_id")

        metadata = hit.metadata
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise BrowserRetrievalError("hit metadata must be a JSON object")

        heading_path = metadata.get("headingPath", [])
        if not isinstance(heading_path, list) or not all(isinstance(item, str) for item in heading_path):
            raise BrowserRetrievalError("hit metadata headingPath must be a list of strings")

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


def _as_directory_url(parsed_root: ParseResult) -> ParseResult:
    path = parsed_root.path if parsed_root.path.endswith("/") else f"{parsed_root.path}/"
    return parsed_root._replace(path=path)
