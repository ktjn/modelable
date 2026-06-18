from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash


def emit_openmetadata(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit OpenMetadata ingestion format for domains, models, and lineage."""
    artifacts: list[EmittedArtifact] = []

    # Simple OpenMetadata representation of domains
    for domain in workspace.mdl.domains:
        artifact_id = f"{domain.name}.openmetadata"
        om_data = {
            "name": domain.name,
            "description": domain.description,
            "owner": domain.owner,
            "assets": [],  # Models and projections go here
            "lineage": [],  # Lineage goes here
        }

        # Add models/projections as assets
        for projection_name, _versions in domain.projections.items():
            om_data["assets"].append(
                {
                    "name": projection_name,
                    "kind": "projection",
                }
            )

        path = out_dir / f"{artifact_id}.json"
        content_hash = compute_content_hash(om_data)

        artifacts.append(
            EmittedArtifact(
                target="openmetadata",
                ref=f"{domain.name}",
                artifact_id=artifact_id,
                path=path,
                content=om_data,
                content_hash=content_hash,
                warnings=[],
            )
        )

    return artifacts
