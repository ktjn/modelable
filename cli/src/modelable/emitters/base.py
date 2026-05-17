from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EmittedArtifact:
    target: str
    ref: str          # "domain.Name@version"
    artifact_id: str  # "domain.Name.vVersion"
    path: Path
    content: dict | str
    warnings: list[str] = field(default_factory=list)
