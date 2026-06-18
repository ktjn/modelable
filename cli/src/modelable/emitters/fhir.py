from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact
from modelable.parser.ir import (
    DomainDef,
    ProjectionVersion,
)


def emit_fhir_profile(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit FHIR R4 StructureDefinition profiles for every projection."""
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for version in versions:
                artifacts.append(_emit_projection(domain, projection_name, version, out_dir))
    return artifacts


def _emit_projection(
    domain: DomainDef, projection_name: str, version: ProjectionVersion, out_dir: Path
) -> EmittedArtifact:
    # Minimal FHIR StructureDefinition
    artifact_id = f"{domain.name}.{projection_name}.v{version.version}"

    # Placeholder implementation of StructureDefinition
    struct_def = {
        "resourceType": "StructureDefinition",
        "url": f"http://modelable.io/fhir/StructureDefinition/{artifact_id}",
        "version": str(version.version),
        "name": projection_name,
        "status": "draft",
        "fhirVersion": "4.0.1",
        "kind": "resource",
        "derivation": "constraint",
        "snapshot": {"element": []},
    }

    path = out_dir / f"{artifact_id}.json"
    import json

    content = json.dumps(struct_def, indent=2, ensure_ascii=False) + "\n"

    return EmittedArtifact(path=path, content=content, warnings=[])
