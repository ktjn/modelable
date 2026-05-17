from __future__ import annotations

from modelable.compiler.workspace import Workspace
from modelable.llm.context import parse_model_ref


def recommend_for_model(workspace: Workspace, ref: str | None = None, consumer: str | None = None) -> str:
    if ref is None:
        return "Provide a model ref like `customer.Customer@1` to get a targeted recommendation."
    model_ref = parse_model_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
    if domain is None:
        return f"Unknown domain: {model_ref.domain}"
    versions = domain.models.get(model_ref.name)
    if not versions:
        return f"Unknown model: {model_ref.domain}.{model_ref.name}"
    version = next((item for item in versions if item.version == model_ref.version), None)
    if version is None:
        return f"Unknown model version: {ref}"

    lines = [f"Recommendations for {ref}:"]
    if consumer:
        lines.append(f"- draft a projection for consumer `{consumer}` with explicit lineage")
    if any(field.is_pii for field in version.fields):
        lines.append("- preserve governance metadata or exclude PII from downstream projections")
    if any(field.classification and field.classification.value in {"confidential", "secret"} for field in version.fields):
        lines.append("- keep classification on derived fields and avoid weakening it in projections")
    if len(version.fields) > 10:
        lines.append("- consider splitting the model into a smaller core entity plus value objects")
    lines.append("- pin version references explicitly when generating imports or projections")
    return "\n".join(lines)

