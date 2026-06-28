from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from modelable.llm.engine import AttachResult, attach_external_version

SUPPORTED_SPEC_KINDS = {"dbt", "fhir", "odcs"}


class SpecSourceError(RuntimeError):
    """Raised when a spec source cannot be resolved."""


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


def evaluate_spec(
    workspace_path: Path,
    entry: SpecEntry,
    *,
    write: bool = False,
    token: str | None = None,
) -> SpecEvaluation:
    try:
        source_text, source_path = _resolve_source(workspace_path, entry, token=token)
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


def _spec_cache_dir(workspace_path: Path, spec_id: str) -> Path:
    sanitized = _sanitize_id(spec_id)
    return workspace_path / ".modelable" / "specs-cache" / sanitized


def _sanitize_id(spec_id: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in spec_id)


def _is_remote_source(source: str) -> bool:
    return source.startswith(("http://", "https://"))


_TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
_RETRY_DELAYS = (1.0, 3.0)


def _resolve_source(
    workspace_path: Path,
    entry: SpecEntry,
    *,
    token: str | None = None,
) -> tuple[str, Path]:
    if _is_remote_source(entry.source):
        content, path, _stale = _fetch_remote_source(entry.source, workspace_path, entry.id, token=token)
        return content, path
    path = _resolve_local_source_path(workspace_path, entry.source)
    return path.read_text(encoding="utf-8"), path


def _fetch_remote_source(
    url: str,
    workspace_path: Path,
    spec_id: str,
    *,
    token: str | None = None,
) -> tuple[str, Path, bool]:
    """Fetch a remote spec URL.

    Returns (content, cache_path, stale) where stale is True when the
    response came from a prior cached copy because the live fetch failed.
    Retries up to 3 attempts on transient HTTP errors (5xx, 429) and
    URLError before falling back to stale cache.
    """
    cache_dir = _spec_cache_dir(workspace_path, spec_id)
    cache_path = cache_dir / "source"
    cache_dir.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    last_exc: Exception | None = None
    for _attempt, delay in enumerate((*_RETRY_DELAYS, None)):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read().decode("utf-8")
            cache_path.write_text(content, encoding="utf-8")
            return content, cache_path, False
        except urllib.error.HTTPError as exc:
            if exc.code not in _TRANSIENT_HTTP_CODES:
                raise SpecSourceError(f"Failed to fetch remote spec {url}: HTTP {exc.code} {exc.reason}") from exc
            last_exc = exc
        except (urllib.error.URLError, OSError) as exc:
            last_exc = exc
        if delay is not None:
            time.sleep(delay)

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8"), cache_path, True

    if isinstance(last_exc, urllib.error.HTTPError):
        raise SpecSourceError(
            f"Failed to fetch remote spec {url}: HTTP {last_exc.code} {last_exc.reason}"
        ) from last_exc
    raise SpecSourceError(f"Failed to fetch remote spec {url}: {last_exc}") from last_exc


def _resolve_local_source_path(workspace_path: Path, source: str) -> Path:
    path = Path(source)
    if path.is_absolute():
        return path
    return workspace_path / path


def _entry_from_dict(item: dict[str, object]) -> SpecEntry:
    return SpecEntry(
        id=str(item["id"]),
        kind=str(item["kind"]),
        source=str(item["source"]),
        ref=str(item["ref"]),
        source_name=str(item["source_name"]) if item.get("source_name") is not None else None,
        update_policy=str(item.get("update_policy") or "preview"),
    )


def change_dicts(result: AttachResult) -> list[dict[str, object]]:
    return [asdict(change) for change in result.changes]
