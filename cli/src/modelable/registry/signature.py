from __future__ import annotations

import hashlib

from modelable.parser.ir import ModelVersion, ProjectionVersion


def compute_version_signature(domain_name: str, model_name: str, version: ModelVersion | ProjectionVersion) -> str:
    """Return the canonical SHA-256 signature for a published model or projection version."""
    from modelable.llm.render import render_model_version, render_projection_version

    if isinstance(version, ModelVersion):
        text = render_model_version(domain_name, model_name, _sorted_model_version(version))
    elif isinstance(version, ProjectionVersion):
        text = render_projection_version(domain_name, model_name, _sorted_projection_version(version))
    else:
        raise TypeError(f"unsupported version type: {type(version)!r}")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sorted_model_version(version: ModelVersion) -> ModelVersion:
    return version.model_copy(update={"fields": sorted(version.fields, key=lambda field: field.name)})


def _sorted_projection_version(version: ProjectionVersion) -> ProjectionVersion:
    return version.model_copy(update={"fields": sorted(version.fields, key=lambda field: field.name)})
