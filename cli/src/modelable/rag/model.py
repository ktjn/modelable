from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DocumentationChunk:
    external_id: str
    source_path: str
    url: str
    language: str
    title: str
    heading: str | None
    heading_path: list[str]
    content: str
    chunk_index: int
