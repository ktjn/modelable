from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class WriteProvenance:
    command: str
    artifact_path: str
    provider: str
    model: str
    validation_status: str
    diagnostics_repaired: int
    inputs: dict[str, str]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def build_write_provenance(
    *,
    command: str,
    artifact_path: Path,
    provider: str,
    model: str,
    validation_status: str,
    diagnostics_repaired: int,
    inputs: dict[str, str],
) -> WriteProvenance:
    return WriteProvenance(
        command=command,
        artifact_path=str(artifact_path),
        provider=provider,
        model=model,
        validation_status=validation_status,
        diagnostics_repaired=diagnostics_repaired,
        inputs=inputs,
    )


def provenance_sidecar_path(artifact_path: Path) -> Path:
    return artifact_path.with_name(f"{artifact_path.name}.provenance.json")


def render_write_provenance(provenance: WriteProvenance) -> str:
    return json.dumps(provenance.as_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_provenance_sidecar(artifact_path: Path, provenance: WriteProvenance) -> Path:
    sidecar_path = provenance_sidecar_path(artifact_path)
    sidecar_path.write_text(render_write_provenance(provenance), encoding="utf-8")
    return sidecar_path
