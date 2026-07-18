from __future__ import annotations

from modelable.compiler.workspace import Workspace
from modelable.llm.context import ModelRef, parse_model_ref
from modelable.llm.conversation_plan import QueryKind, QueryPlan
from modelable.parser.ir import ProjectionField


def answer_question(workspace: Workspace, question: str) -> str:
    typed_plan = _legacy_query_plan(question)
    if typed_plan is not None:
        # Keep the adapter local to preserve a one-way import boundary.
        from modelable.llm.workspace_query import WorkspaceQueryService

        return WorkspaceQueryService(workspace).execute(typed_plan).text

    lower = question.lower().strip()
    if "owner" in lower or "who owns" in lower:
        return _answer_owner_question(workspace, question)
    if "lineage" in lower or "where did" in lower:
        return _answer_lineage_question(workspace, question)
    if "depend" in lower or "impact" in lower or "break" in lower:
        return _answer_dependency_question(workspace, question)
    if "field" in lower or "model" in lower:
        return _answer_model_question(workspace, question)
    return "I can answer ownership, lineage, dependency, and validation questions when you point me at a model or projection."


def _legacy_query_plan(question: str) -> QueryPlan | None:
    lower = question.lower().strip()
    ref = _extract_ref(question)
    if "valid" in lower or "diagnostic" in lower:
        return QueryPlan(query_kind="validation", refs=[], question=question)
    if ref is None:
        return None
    refs = [f"{ref.domain}.{ref.name}@{ref.version}"]
    if "owner" in lower or "who owns" in lower:
        query_kind: QueryKind = "ownership"
    elif "lineage" in lower or "where did" in lower:
        query_kind = "lineage"
    elif "depend" in lower or "impact" in lower or "break" in lower:
        query_kind = "dependents"
    elif "index" in lower or "look it up" in lower:
        query_kind = "indexes"
    elif "field" in lower or "model" in lower or "projection" in lower or "describe" in lower:
        query_kind = "summary"
    else:
        return None
    return QueryPlan(query_kind=query_kind, refs=refs, question=question)


def _answer_owner_question(workspace: Workspace, question: str) -> str:
    ref = _extract_ref(question)
    if ref:
        domain = next((d for d in workspace.mdl.domains if d.name == ref.domain), None)
        if domain is None:
            return f"Unknown domain: {ref.domain}"
        if ref.name in domain.models:
            owner = domain.owner or "unspecified"
            return f"{ref.domain}.{ref.name}@{ref.version} is owned by {owner}."
        if ref.name in domain.projections:
            owner = domain.owner or "unspecified"
            return f"{ref.domain}.{ref.name}@{ref.version} is owned by {owner}."
    return _domain_owners(workspace)


def _answer_lineage_question(workspace: Workspace, question: str) -> str:
    ref = _extract_ref(question)
    if not ref:
        return "Ask about a specific projection ref like `billing.BillingCustomer@1`."
    domain = next((d for d in workspace.mdl.domains if d.name == ref.domain), None)
    if domain is None:
        return f"Unknown domain: {ref.domain}"
    versions = domain.projections.get(ref.name)
    if not versions:
        return f"Unknown projection: {ref.domain}.{ref.name}"
    version = next((item for item in versions if item.version == ref.version), None)
    if version is None:
        return f"Unknown projection version: {ref.domain}.{ref.name}@{ref.version}"
    lines = [f"{ref.domain}.{ref.name}@{ref.version} lineage:"]
    for field in version.fields:
        lines.append(f"- {field.name}: {_field_lineage(field)}")
    return "\n".join(lines)


def _answer_dependency_question(workspace: Workspace, question: str) -> str:
    ref = _extract_ref(question)
    if not ref:
        return "Ask about a specific model ref like `customer.Customer@1`."
    dependents: list[str] = []
    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for version in versions:
                if version.source.model == f"{ref.domain}.{ref.name}" or any(
                    join.model == f"{ref.domain}.{ref.name}" for join in version.joins
                ):
                    dependents.append(f"{domain.name}.{projection_name}@{version.version}")
    if not dependents:
        return f"No projections currently depend on {ref.domain}.{ref.name}@{ref.version}."
    return "Dependents:\n" + "\n".join(f"- {item}" for item in dependents)


def _answer_model_question(workspace: Workspace, question: str) -> str:
    ref = _extract_ref(question)
    if ref:
        return _model_summary(workspace, ref.domain, ref.name, ref.version)
    return _workspace_summary(workspace)


def _extract_ref(question: str) -> ModelRef | None:
    tokens = question.replace("?", " ").replace(",", " ").split()
    for token in tokens:
        if "@" in token and "." in token:
            try:
                return parse_model_ref(token.strip("`"))
            except Exception:
                continue
    return None


def _model_summary(workspace: Workspace, domain_name: str, model_name: str, version: int) -> str:
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return f"Unknown domain: {domain_name}"
    versions = domain.models.get(model_name)
    if not versions:
        return f"Unknown model: {domain_name}.{model_name}"
    mv = next((item for item in versions if item.version == version), None)
    if mv is None:
        return f"Unknown model version: {domain_name}.{model_name}@{version}"
    lines = [f"{domain_name}.{model_name}@{version} ({mv.model_kind.value}, {mv.change_kind.value})"]
    if domain.owner:
        lines.append(f"owner: {domain.owner}")
    for field in mv.fields:
        lines.append(f"- {field.name}")
    return "\n".join(lines)


def _domain_owners(workspace: Workspace) -> str:
    lines = []
    for domain in workspace.mdl.domains:
        owner = domain.owner or "unspecified"
        lines.append(f"{domain.name}: {owner}")
    return "\n".join(lines) if lines else "No domains found."


def _workspace_summary(workspace: Workspace) -> str:
    lines = []
    for domain in workspace.mdl.domains:
        lines.append(f"{domain.name}: {len(domain.models)} models, {len(domain.projections)} projections")
    return "\n".join(lines) if lines else "Workspace is empty."


def _field_lineage(field: ProjectionField) -> str:
    mapping = field.mapping
    if mapping.kind == "direct":
        return f"direct {mapping.source_alias}.{mapping.source_field}"
    return f"computed {mapping.expression}"
