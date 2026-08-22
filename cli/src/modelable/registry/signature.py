from __future__ import annotations

import hashlib

from modelable.parser.ir import EnumProjectionDecl, ModelVersion, ProjectionVersion, SemanticTypeDecl


def compute_version_signature(domain_name: str, model_name: str, version: ModelVersion | ProjectionVersion) -> str:
    """Return the canonical SHA-256 signature for a published model or projection version."""
    from modelable.compiler.render import render_signature_model_version, render_signature_projection_version

    if isinstance(version, ModelVersion):
        text = render_signature_model_version(domain_name, model_name, _sorted_model_version(version))
    elif isinstance(version, ProjectionVersion):
        text = render_signature_projection_version(domain_name, model_name, _sorted_projection_version(version))
    else:
        raise TypeError(f"unsupported version type: {type(version)!r}")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_semantic_signature(domain_name: str, declaration: SemanticTypeDecl) -> str:
    """Return the canonical SHA-256 signature for a semantic type declaration version."""
    from modelable.compiler.render import render_signature_semantic_type

    text = render_signature_semantic_type(domain_name, declaration)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_enum_projection_signature(domain_name: str, projection: EnumProjectionDecl) -> str:
    """Return the canonical SHA-256 signature for an enum projection version."""
    from modelable.compiler.render import render_signature_enum_projection

    text = render_signature_enum_projection(domain_name, projection)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sorted_model_version(version: ModelVersion) -> ModelVersion:
    return version.model_copy(update={"fields": sorted(version.fields, key=lambda field: field.name)})


def _sorted_projection_version(version: ProjectionVersion) -> ProjectionVersion:
    return version.model_copy(update={"fields": sorted(version.fields, key=lambda field: field.name)})
