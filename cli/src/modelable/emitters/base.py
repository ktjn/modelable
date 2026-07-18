from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ArtifactContent = dict[str, Any] | str | bytes


@dataclass
class EmittedArtifact:
    target: str
    ref: str  # "domain.Name@version"
    artifact_id: str  # "domain.Name.vVersion"
    path: Path
    content: ArtifactContent
    content_hash: str
    warnings: list[str] = field(default_factory=list)


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
