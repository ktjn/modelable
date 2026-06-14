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


@dataclass(frozen=True)
class AttachmentRecord:
    ref: str
    source_format: str
    source_name: str
    source_path: str
    source_hash: str
    from_version: int
    to_version: int | None
    change_kind: str | None
    changes: list[dict[str, object]]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def attachment_sidecar_path(artifact_path: Path) -> Path:
    return artifact_path.with_name(f"{artifact_path.name}.attachments.json")


def write_attachment_record(artifact_path: Path, record: AttachmentRecord) -> Path:
    sidecar_path = attachment_sidecar_path(artifact_path)
    records: list[dict[str, object]] = []
    if sidecar_path.exists():
        records = json.loads(sidecar_path.read_text(encoding="utf-8"))
    records.append(record.as_dict())
    sidecar_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return sidecar_path
