from __future__ import annotations

import json
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.parser.ir import MdlFile, ModelVersion, NamedType, SemanticTypeDecl
from modelable.registry.signature import compute_version_signature


def emit_registry_manifest(
    workspace: Workspace,
    out_dir: Path,
    *,
    registry_ids: dict[str, int] | None = None,
) -> list[EmittedArtifact]:
    """Emit one deterministic contract inventory for every compiled declaration."""
    entries: list[dict[str, object]] = []
    for domain in sorted(workspace.mdl.domains, key=lambda item: item.name):
        for name, model_versions in sorted(domain.models.items()):
            for model_version in sorted(model_versions, key=lambda item: item.version):
                entries.append(
                    _entry(
                        domain.name,
                        name,
                        model_version.version,
                        "model",
                        compute_version_signature(domain.name, name, model_version),
                        registry_id=_model_registry_id(workspace.mdl, domain.name, model_version, registry_ids),
                    )
                )
        for name, projection_versions in sorted(domain.projections.items()):
            for projection_version in sorted(projection_versions, key=lambda item: item.version):
                entries.append(
                    _entry(
                        domain.name,
                        name,
                        projection_version.version,
                        "projection",
                        compute_version_signature(domain.name, name, projection_version),
                        registry_id=None,
                    )
                )
        for declaration in sorted(domain.semantic_types, key=lambda item: item.name):
            ref = f"{domain.name}.{declaration.name}"
            entries.append(
                {
                    "kind": "semantic",
                    "name": declaration.name,
                    "ref": ref,
                    "registry_id": (registry_ids or {}).get(ref) if declaration.registry else None,
                    "registry": declaration.registry,
                }
            )

    payload = {"format": "modelable.registry.v1", "contracts": entries}
    content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return [
        EmittedArtifact(
            target="registry",
            ref="workspace#registry",
            artifact_id="registry",
            path=out_dir / "registry.json",
            content=content,
            content_hash=compute_content_hash(content),
        )
    ]


def _entry(
    domain: str,
    name: str,
    version: int,
    kind: str,
    signature: str,
    *,
    registry_id: int | None,
) -> dict[str, object]:
    return {
        "domain": domain,
        "kind": kind,
        "name": name,
        "ref": f"{domain}.{name}@{version}",
        "registry_id": registry_id,
        "schema_version": version,
        "signature": signature,
    }


def _model_registry_id(
    mdl: MdlFile,
    domain_name: str,
    model: ModelVersion,
    registry_ids: dict[str, int] | None,
) -> int | None:
    """Return the allocated identity of a model's registry-backed key type."""
    for field in model.fields:
        if not field.is_key or not isinstance(field.type, NamedType):
            continue
        qualified_name = field.type.name if "." in field.type.name else f"{domain_name}.{field.type.name}"
        declaration = _find_semantic_type(mdl, qualified_name)
        if declaration is not None and declaration.registry:
            return (registry_ids or {}).get(qualified_name)
    return None


def _find_semantic_type(mdl: MdlFile, qualified_name: str) -> SemanticTypeDecl | None:
    domain_name, name = qualified_name.rsplit(".", 1)
    domain = next((item for item in mdl.domains if item.name == domain_name), None)
    return next((item for item in domain.semantic_types if item.name == name), None) if domain else None
