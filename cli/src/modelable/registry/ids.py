from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from modelable.parser.ir import MdlFile


def _qualified_registry_names(mdl: MdlFile) -> list[str]:
    return sorted(
        f"{domain.name}.{decl.name}" for domain in mdl.domains for decl in domain.semantic_types if decl.registry
    )


def allocate_registry_ids(
    mdl: MdlFile,
    existing: dict[str, int],
    *,
    allow_orphaned: bool = False,
) -> dict[str, int]:
    """Allocate deterministic small-integer ids for every `registry: true`
    semantic type, never reassigning or reusing an id already in `existing`.
    """
    declared = set(_qualified_registry_names(mdl))
    orphaned = sorted(name for name in existing if name not in declared)
    if orphaned and not allow_orphaned:
        joined = ", ".join(orphaned)
        raise ValueError(
            f"registry-ids.lock has {len(orphaned)} orphaned id(s) with no matching "
            f"'registry: true' semantic type declaration: {joined}. Pass "
            "--allow-orphaned-registry-ids to keep them reserved (they are never reused)."
        )

    updated = dict(existing)
    next_id = max(existing.values(), default=0) + 1
    for name in sorted(declared - existing.keys()):
        updated[name] = next_id
        next_id += 1
    return updated


def read_lock_file(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    return cast(dict[str, int], json.loads(path.read_text(encoding="utf-8")))


def write_lock_file(path: Path, ids: dict[str, int]) -> None:
    ordered = dict(sorted(ids.items(), key=lambda item: item[1]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
