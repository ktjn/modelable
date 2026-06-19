from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from modelable.llm.engine import AttachResult, attach_external_version

SUPPORTED_SPEC_KINDS = {"dbt", "fhir", "odcs"}


@dataclass(frozen=True)
class SpecEntry:
    id: str
    kind: str
    source: str
    ref: str
    source_name: str | None = None
    update_policy: str = "preview"

    def as_config_dict(self) -> dict[str, str]:
        data = {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "ref": self.ref,
        }
        if self.source_name is not None:
            data["source_name"] = self.source_name
        data["update_policy"] = self.update_policy
        return data


@dataclass(frozen=True)
class SpecEvaluation:
    entry: SpecEntry
    status: str
    source_hash: str | None
    change_kind: str | None
    change_count: int
    result: AttachResult | None = None
    error: str | None = None

    def as_status_dict(self) -> dict[str, object]:
        return {
            "id": self.entry.id,
            "kind": self.entry.kind,
            "source": self.entry.source,
            "ref": self.entry.ref,
            "source_name": self.entry.source_name,
            "status": self.status,
            "source_hash": self.source_hash,
            "change_kind": self.change_kind,
            "change_count": self.change_count,
            "error": self.error,
        }


def spec_config_path(workspace_path: Path) -> Path:
    return workspace_path / ".modelable" / "specs.yml"


def load_spec_config(workspace_path: Path) -> list[SpecEntry]:
    path = spec_config_path(workspace_path)
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs = doc.get("specs") or []
    return [_entry_from_dict(item) for item in specs]


def write_spec_config(workspace_path: Path, specs: list[SpecEntry]) -> Path:
    path = spec_config_path(workspace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"specs": [entry.as_config_dict() for entry in specs]}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def add_spec(workspace_path: Path, entry: SpecEntry) -> Path:
    if entry.kind not in SUPPORTED_SPEC_KINDS:
        supported = ", ".join(sorted(SUPPORTED_SPEC_KINDS))
        raise ValueError(f"Unsupported tracked spec kind '{entry.kind}'. Supported kinds: {supported}")
    specs = load_spec_config(workspace_path)
    if any(item.id == entry.id for item in specs):
        raise ValueError(f"Tracked spec '{entry.id}' already exists")
    specs.append(entry)
    return write_spec_config(workspace_path, specs)


def select_specs(workspace_path: Path, spec_id: str | None) -> list[SpecEntry]:
    specs = load_spec_config(workspace_path)
    if spec_id is None:
        return specs
    selected = [entry for entry in specs if entry.id == spec_id]
    if not selected:
        raise ValueError(f"Tracked spec '{spec_id}' not found")
    return selected


def evaluate_spec(workspace_path: Path, entry: SpecEntry, *, write: bool = False) -> SpecEvaluation:
    try:
        source_path = _resolve_source_path(workspace_path, entry.source)
        source_text = source_path.read_text(encoding="utf-8")
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        result = attach_external_version(
            workspace_path,
            entry.ref,
            source_path,
            entry.kind,
            source_name=entry.source_name,
            write=write,
        )
        status = "drifted" if result.attached else "clean"
        return SpecEvaluation(
            entry=entry,
            status=status,
            source_hash=source_hash,
            change_kind=result.change_kind,
            change_count=len(result.changes),
            result=result,
        )
    except Exception as exc:
        return SpecEvaluation(
            entry=entry,
            status="error",
            source_hash=None,
            change_kind=None,
            change_count=0,
            error=str(exc),
        )


def _entry_from_dict(item: dict[str, object]) -> SpecEntry:
    return SpecEntry(
        id=str(item["id"]),
        kind=str(item["kind"]),
        source=str(item["source"]),
        ref=str(item["ref"]),
        source_name=str(item["source_name"]) if item.get("source_name") is not None else None,
        update_policy=str(item.get("update_policy") or "preview"),
    )


def _resolve_source_path(workspace_path: Path, source: str) -> Path:
    path = Path(source)
    if path.is_absolute():
        return path
    return workspace_path / path


def change_dicts(result: AttachResult) -> list[dict[str, object]]:
    return [asdict(change) for change in result.changes]
