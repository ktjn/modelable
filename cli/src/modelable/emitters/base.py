from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

ArtifactContent = dict[str, Any] | str | bytes


@dataclass
class EmittedArtifact:
    target: str
    ref: str  # "domain.Name@version"
    artifact_id: str  # "domain.Name.vVersion"
    path: PurePath
    content: ArtifactContent
    content_hash: str
    warnings: list[str] = field(default_factory=list)


def artifact_id(domain: str, name: str, version: int) -> str:
    """Stable artifact identifier shared by every target: ``domain.Name.vVersion``."""
    return f"{domain}.{name}.v{version}"


def render_nested_definitions(definitions: dict[str, list[str]]) -> list[str]:
    """Join collected nested type definitions, each preceded by a blank line.

    Shared by the source-code emitters, which all accumulate nested object
    definitions in an insertion-ordered dict while rendering the owning type.
    """
    lines: list[str] = []
    for definition in definitions.values():
        lines.append("")
        lines.extend(definition)
    return lines


def compute_content_hash(content: ArtifactContent) -> str:
    if isinstance(content, bytes):
        return hashlib.sha256(content).hexdigest()
    payload = json.dumps(content, indent=2, ensure_ascii=False) + "\n" if isinstance(content, dict) else content
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_artifact_text(artifact: EmittedArtifact) -> str:
    content = artifact.content
    if isinstance(content, bytes):
        raise TypeError(f"{artifact.target} artifact {artifact.artifact_id} is binary")
    if isinstance(content, dict):
        return json.dumps(content, indent=2, ensure_ascii=False) + "\n"
    return content
