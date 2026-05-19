from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path


@dataclass
class EmittedArtifact:
    target: str
    ref: str          # "domain.Name@version"
    artifact_id: str  # "domain.Name.vVersion"
    path: Path
    content: dict | str
    content_hash: str
    warnings: list[str] = field(default_factory=list)


def compute_content_hash(content: dict | str) -> str:
    if isinstance(content, dict):
        payload = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
    else:
        payload = content
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
