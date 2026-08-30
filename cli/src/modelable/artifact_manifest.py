from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact
from modelable.emitters.targets import get_codegen_target
from modelable.extensions import modelable_version

MANIFEST_NAME = "modelable-artifact-manifest.json"
MANIFEST_FORMAT = "modelable.artifact-manifest.v1"


def build_artifact_manifest(
    workspace: Workspace,
    artifacts: tuple[EmittedArtifact, ...],
    *,
    target: str,
    workspace_root: Path,
    registry_lock: Path,
    output_root: Path,
) -> dict[str, Any]:
    target_profile = get_codegen_target(target)
    extension_descriptor = target_profile.extension_descriptor()
    lock_hash = _sha256(registry_lock) if registry_lock.is_file() else None
    return {
        "format": MANIFEST_FORMAT,
        "compiler": {"name": "modelable", "version": _compiler_version()},
        "inputs": [
            {
                "path": _relative_path(source.path, workspace_root),
                "signature": source.content_hash,
            }
            for source in workspace.sources
            if source.path is not None
        ],
        "snapshot": {"registry_lock": _relative_path(registry_lock, workspace_root), "sha256": lock_hash},
        "plugins": [],
        "extensions": [extension_descriptor.as_dict()],
        "target": {
            "name": target_profile.name,
            "kind": target_profile.kind,
            "status": target_profile.status,
        },
        "artifacts": [
            {
                "path": _relative_path(Path(artifact.path), output_root),
                "ref": artifact.ref,
                "sha256": artifact.content_hash,
            }
            for artifact in artifacts
        ],
        "warnings": sorted({warning for artifact in artifacts for warning in artifact.warnings}),
        "loss_facts": sorted({warning for artifact in artifacts for warning in artifact.warnings}),
    }


def write_artifact_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _compiler_version() -> str:
    return modelable_version()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
