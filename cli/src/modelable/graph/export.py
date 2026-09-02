from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.identity import declaration_id, semantic_path
from modelable.llm.context import ModelRef, parse_model_ref
from modelable.parser.ir import (
    ArrayType,
    DirectMapping,
    DomainDef,
    EnumProjectionDecl,
    EnumRefType,
    FieldDef,
    FieldType,
    MapType,
    ModelVersion,
    NamedType,
    ObjectType,
    ProjectionField,
    ProjectionVersion,
    RefType,
    SemanticTypeDecl,
    UnionType,
    VersionMin,
    VersionSpec,
)
from modelable.registry.resolver import (
    AmbiguousSemanticTypeError,
    resolve_model_ref,
    resolve_semantic_type_ref,
)

_NODE_KIND_ORDER = {
    "domain": 0,
    "model": 1,
    "semantic_type": 2,
    "model_version": 3,
    "field": 4,
    "projection": 5,
    "projection_version": 6,
    "projection_field": 7,
    "enum_projection": 8,
}
_EDGE_KIND_ORDER = {
    "owns": 0,
    "version_of": 1,
    "contains_field": 2,
    "has_projection": 3,
    "version_of_projection": 4,
    "maps_to": 5,
    "references": 6,
    "projects_from": 7,
}
_EDGE_GROUP_ORDER = {
    ("owns", "domain"): 0,
    ("version_of", "model"): 1,
    ("contains_field", "model_version"): 2,
    ("has_projection", "domain"): 3,
    ("version_of_projection", "projection"): 4,
    ("contains_field", "projection_version"): 5,
    ("maps_to", "projection_field"): 6,
    ("references", "field"): 7,
    ("projects_from", "enum_projection"): 8,
}


def build_graph_export(workspace: Workspace, focus: str | None = None) -> dict[str, Any]:
    """Build a canonical JSON graph export for the normalized workspace."""
    builder = _GraphBuilder()
    for domain in workspace.mdl.domains:
        _add_domain(builder, workspace, domain)

    graph = {
        "kind": "workspace_graph",
        "nodes": _sorted_nodes(builder.nodes.values()),
        "edges": _sorted_edges(builder.edges.values()),
    }
    if focus is None:
        return graph

    focus_ref = parse_model_ref(focus)
    selected_ids = _select_focus_subgraph(builder, focus_ref)
    return {
        "kind": "workspace_graph",
        "nodes": _sorted_nodes(node for node in builder.nodes.values() if node["id"] in selected_ids),
        "edges": _sorted_edges(
            edge for edge in builder.edges.values() if edge["source"] in selected_ids and edge["target"] in selected_ids
        ),
    }


def write_graph_export(graph: dict[str, Any], out_path: Path) -> None:
    out_path.write_text(
        json.dumps(graph, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class _GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.parents: dict[str, tuple[str, ...]] = {}
        self.edges_by_source: dict[str, list[dict[str, Any]]] = {}
        self.edges_by_target: dict[str, list[dict[str, Any]]] = {}

    def add_node(self, node: dict[str, Any], *, parents: Iterable[str] = ()) -> dict[str, Any]:
        node_id = node["id"]
        if node_id not in self.nodes:
            self.nodes[node_id] = node
        if node_id not in self.parents:
            self.parents[node_id] = tuple(parents)
        return self.nodes[node_id]

    def add_edge(self, source: str, target: str, kind: str) -> dict[str, Any]:
        key = (kind, source, target)
        if key not in self.edges:
            edge = {"kind": kind, "source": source, "target": target}
            self.edges[key] = edge
            self.edges_by_source.setdefault(source, []).append(edge)
            self.edges_by_target.setdefault(target, []).append(edge)
        return self.edges[key]


def _sorted_nodes(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(nodes, key=lambda item: (_NODE_KIND_ORDER.get(item["kind"], 99), item["id"]))


def _sorted_edges(edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        edges,
        key=_edge_sort_key,
    )


def _edge_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    source_kind = item["source"].split(":", 1)[0]
    rank = _EDGE_GROUP_ORDER.get((item["kind"], source_kind), _EDGE_KIND_ORDER.get(item["kind"], 99))
    return (rank, item["source"], item["target"])


def _add_domain(builder: _GraphBuilder, workspace: Workspace, domain: DomainDef) -> None:
    domain_id = f"domain:{domain.name}"
    builder.add_node(
        {
            "id": domain_id,
            "kind": "domain",
            "label": domain.name,
            "domain": domain.name,
            "target_ref": domain.name,
        }
    )

    for model_name, versions in domain.models.items():
        _add_model(builder, workspace, domain_id, domain.name, model_name, versions)

    for semantic_type in sorted(domain.semantic_types, key=lambda item: (item.name, item.version)):
        _add_semantic_type(builder, workspace, domain_id, domain.name, semantic_type)

    for enum_projection in sorted(domain.enum_projections, key=lambda item: (item.name, item.version)):
        _add_enum_projection(builder, workspace, domain_id, domain.name, enum_projection)

    for projection_name, projection_versions in domain.projections.items():
        _add_projection(builder, workspace, domain_id, domain.name, projection_name, projection_versions)


def _add_model(
    builder: _GraphBuilder,
    workspace: Workspace,
    domain_id: str,
    domain_name: str,
    model_name: str,
    versions: list[ModelVersion],
) -> None:
    model_id = f"model:{domain_name}.{model_name}"
    builder.add_node(
        {
            "id": model_id,
            "kind": "model",
            "label": model_name,
            "domain": domain_name,
            "name": model_name,
            "target_ref": f"{domain_name}.{model_name}",
        },
        parents=(domain_id,),
    )
    builder.add_edge(domain_id, model_id, "owns")

    for version in sorted(versions, key=lambda item: item.version):
        _add_model_version(builder, workspace, model_id, domain_name, model_name, version)


def _add_model_version(
    builder: _GraphBuilder,
    workspace: Workspace,
    model_id: str,
    domain_name: str,
    model_name: str,
    version: ModelVersion,
) -> None:
    version_id = f"model_version:{domain_name}.{model_name}@{version.version}"
    builder.add_node(
        {
            "id": version_id,
            "kind": "model_version",
            "label": f"{model_name}@{version.version}",
            "domain": domain_name,
            "name": model_name,
            "version": version.version,
            "change_kind": version.change_kind.value,
            "model_kind": version.model_kind.value,
            "target_ref": declaration_id(domain_name, model_name, version.version),
        },
        parents=(model_id,),
    )
    builder.add_edge(model_id, version_id, "version_of")

    for field in version.fields:
        _add_model_field(builder, workspace, version_id, domain_name, model_name, version.version, field)


def _add_model_field(
    builder: _GraphBuilder,
    workspace: Workspace,
    version_id: str,
    domain_name: str,
    model_name: str,
    version: int,
    field: FieldDef,
) -> None:
    field_id = "field:" + semantic_path(declaration_id(domain_name, model_name, version), field.name)
    builder.add_node(
        {
            "id": field_id,
            "kind": "field",
            "label": field.name,
            "domain": domain_name,
            "name": model_name,
            "version": version,
            "field": field.name,
            "optional": field.optional,
            "nullable": field.nullable,
            "target_ref": semantic_path(declaration_id(domain_name, model_name, version), field.name),
        },
        parents=(version_id,),
    )
    builder.add_edge(version_id, field_id, "contains_field")
    for ref_type in _iter_ref_types(field.type):
        if "." not in ref_type.target:
            continue
        target_id = _resolve_version_ref(
            workspace,
            ref_type.target,
            ref_type.version if ref_type.version is not None else VersionMin(min_inclusive=1),
        )
        builder.add_edge(field_id, f"model_version:{target_id}", "references")
    for type_name, exact_version in _iter_semantic_type_refs(field.type):
        try:
            declaring_domain, declaration = resolve_semantic_type_ref(
                workspace.mdl,
                domain_name,
                type_name,
                exact_version=exact_version,
            )
        except LookupError as semantic_error:
            if isinstance(semantic_error, AmbiguousSemanticTypeError) or exact_version is not None:
                raise
            try:
                resolved_model = _resolve_named_model_ref(workspace, domain_name, type_name)
            except LookupError:
                raise semantic_error from semantic_error
            builder.add_edge(
                field_id,
                f"model_version:{resolved_model.domain_name}.{resolved_model.model_name}@{resolved_model.version.version}",
                "references",
            )
        else:
            builder.add_edge(
                field_id,
                f"semantic_type:{declaration_id(declaring_domain, declaration.name, declaration.version)}",
                "references",
            )


def _add_semantic_type(
    builder: _GraphBuilder,
    workspace: Workspace,
    domain_id: str,
    domain_name: str,
    declaration: SemanticTypeDecl,
) -> None:
    type_id = f"semantic_type:{declaration_id(domain_name, declaration.name, declaration.version)}"
    builder.add_node(
        {
            "id": type_id,
            "kind": "semantic_type",
            "label": f"{declaration.name}@{declaration.version}",
            "domain": domain_name,
            "name": declaration.name,
            "version": declaration.version,
            "target_ref": declaration_id(domain_name, declaration.name, declaration.version),
        },
        parents=(domain_id,),
    )
    builder.add_edge(domain_id, type_id, "owns")
    for type_name, exact_version in _iter_semantic_type_refs(declaration.underlying):
        declaring_domain, target = resolve_semantic_type_ref(
            workspace.mdl,
            domain_name,
            type_name,
            exact_version=exact_version,
        )
        builder.add_edge(
            type_id,
            f"semantic_type:{declaration_id(declaring_domain, target.name, target.version)}",
            "references",
        )


def _add_enum_projection(
    builder: _GraphBuilder,
    workspace: Workspace,
    domain_id: str,
    domain_name: str,
    declaration: EnumProjectionDecl,
) -> None:
    projection_id = f"enum_projection:{declaration_id(domain_name, declaration.name, declaration.version)}"
    source_domain, source = resolve_semantic_type_ref(
        workspace.mdl,
        domain_name,
        declaration.source_name,
        exact_version=declaration.source_version,
    )
    builder.add_node(
        {
            "id": projection_id,
            "kind": "enum_projection",
            "label": f"{declaration.name}@{declaration.version}",
            "domain": domain_name,
            "name": declaration.name,
            "version": declaration.version,
            "source_ref": declaration_id(source_domain, source.name, source.version),
            "target_ref": declaration_id(domain_name, declaration.name, declaration.version),
        },
        parents=(domain_id,),
    )
    builder.add_edge(domain_id, projection_id, "has_projection")
    builder.add_edge(
        projection_id,
        f"semantic_type:{declaration_id(source_domain, source.name, source.version)}",
        "projects_from",
    )


def _iter_ref_types(field_type: FieldType) -> list[RefType]:
    if isinstance(field_type, RefType):
        return [field_type]
    if isinstance(field_type, ArrayType):
        return _iter_ref_types(field_type.item)
    if isinstance(field_type, MapType):
        return _iter_ref_types(field_type.key) + _iter_ref_types(field_type.value)
    if isinstance(field_type, ObjectType):
        refs: list[RefType] = []
        for field in field_type.fields:
            refs.extend(_iter_ref_types(field.type))
        return refs
    if isinstance(field_type, UnionType):
        union_refs: list[RefType] = []
        for variant in field_type.variants:
            union_refs.extend(_iter_ref_types(variant.type))
        return union_refs
    return []


def _iter_semantic_type_refs(field_type: FieldType) -> list[tuple[str, int | None]]:
    if isinstance(field_type, NamedType):
        return [(field_type.name, None)]
    if isinstance(field_type, EnumRefType):
        return [(field_type.name, field_type.version)]
    if isinstance(field_type, ArrayType):
        return _iter_semantic_type_refs(field_type.item)
    if isinstance(field_type, MapType):
        return _iter_semantic_type_refs(field_type.key) + _iter_semantic_type_refs(field_type.value)
    if isinstance(field_type, ObjectType):
        refs: list[tuple[str, int | None]] = []
        for field in field_type.fields:
            refs.extend(_iter_semantic_type_refs(field.type))
        return refs
    if isinstance(field_type, UnionType):
        refs = []
        for variant in field_type.variants:
            refs.extend(_iter_semantic_type_refs(variant.type))
        return refs
    return []


def _add_projection(
    builder: _GraphBuilder,
    workspace: Workspace,
    domain_id: str,
    domain_name: str,
    projection_name: str,
    versions: list[ProjectionVersion],
) -> None:
    projection_id = f"projection:{domain_name}.{projection_name}"
    builder.add_node(
        {
            "id": projection_id,
            "kind": "projection",
            "label": projection_name,
            "domain": domain_name,
            "name": projection_name,
            "target_ref": f"{domain_name}.{projection_name}",
        },
        parents=(domain_id,),
    )
    builder.add_edge(domain_id, projection_id, "has_projection")

    for version in sorted(versions, key=lambda item: item.version):
        _add_projection_version(
            builder,
            workspace,
            projection_id,
            domain_name,
            projection_name,
            version,
        )


def _add_projection_version(
    builder: _GraphBuilder,
    workspace: Workspace,
    projection_id: str,
    domain_name: str,
    projection_name: str,
    version: ProjectionVersion,
) -> None:
    version_id = f"projection_version:{domain_name}.{projection_name}@{version.version}"
    source_ref = _resolve_version_ref(workspace, version.source.model, version.source.version)
    builder.add_node(
        {
            "id": version_id,
            "kind": "projection_version",
            "label": f"{projection_name}@{version.version}",
            "domain": domain_name,
            "name": projection_name,
            "version": version.version,
            "source_ref": source_ref,
            "target_ref": declaration_id(domain_name, projection_name, version.version),
        },
        parents=(projection_id,),
    )
    builder.add_edge(projection_id, version_id, "version_of_projection")

    for field in version.fields:
        _add_projection_field(
            builder,
            workspace,
            version_id,
            domain_name,
            projection_name,
            version,
            field,
        )


def _add_projection_field(
    builder: _GraphBuilder,
    workspace: Workspace,
    version_id: str,
    domain_name: str,
    projection_name: str,
    projection_version: ProjectionVersion,
    field: ProjectionField,
) -> None:
    field_id = "projection_field:" + semantic_path(
        declaration_id(domain_name, projection_name, projection_version.version), field.name
    )
    node: dict[str, Any] = {
        "id": field_id,
        "kind": "projection_field",
        "label": field.name,
        "domain": domain_name,
        "name": projection_name,
        "version": projection_version.version,
        "field": field.name,
        "target_ref": semantic_path(
            declaration_id(domain_name, projection_name, projection_version.version), field.name
        ),
    }
    if isinstance(field.mapping, DirectMapping):
        node["mapping_kind"] = "direct"
        source_ref = _resolve_direct_mapping_ref(
            workspace,
            projection_version,
            field.mapping.source_alias,
            field.mapping.source_field,
        )
        node["source_ref"] = source_ref
    else:
        node["mapping_kind"] = "computed"

    builder.add_node(node, parents=(version_id,))
    builder.add_edge(version_id, field_id, "contains_field")

    if isinstance(field.mapping, DirectMapping):
        source_field_id = source_ref
        source_node_id = source_field_id.replace("source_ref:", "field:")
        builder.add_edge(field_id, source_node_id, "maps_to")


def _resolve_version_ref(workspace: Workspace, model_ref: str, version_spec: VersionSpec | int) -> str:
    resolved = resolve_model_ref(workspace.mdl, model_ref, version_spec)
    return declaration_id(resolved.domain_name, resolved.model_name, resolved.version.version)


def _resolve_direct_mapping_ref(
    workspace: Workspace,
    projection_version: ProjectionVersion,
    source_alias: str,
    source_field: str,
) -> str:
    source_model_ref = _alias_map(projection_version).get(source_alias)
    if source_model_ref is None:
        raise LookupError(f"unknown source alias '{source_alias}' in projection {projection_version.version}")
    resolved = resolve_model_ref(workspace.mdl, source_model_ref.model, source_model_ref.version)
    field_name = source_field
    return "source_ref:" + semantic_path(
        declaration_id(resolved.domain_name, resolved.model_name, resolved.version.version), field_name
    )


def _alias_map(projection_version: ProjectionVersion) -> dict[str, Any]:
    aliases: dict[str, Any] = {projection_version.source.alias: projection_version.source}
    for join in projection_version.joins:
        aliases[join.alias] = join
    return aliases


def _select_focus_subgraph(builder: _GraphBuilder, focus_ref: ModelRef) -> set[str]:
    model_version_id = f"model_version:{focus_ref.domain}.{focus_ref.name}@{focus_ref.version}"
    projection_version_id = f"projection_version:{focus_ref.domain}.{focus_ref.name}@{focus_ref.version}"
    model_node_id = f"model:{focus_ref.domain}.{focus_ref.name}"
    projection_node_id = f"projection:{focus_ref.domain}.{focus_ref.name}"

    focus_kind: str | None = None
    seed_ids: set[str] = set()
    if model_version_id in builder.nodes:
        focus_kind = "model"
        seed_ids.update(
            {
                model_node_id,
                model_version_id,
                *(
                    node_id
                    for node_id, node in builder.nodes.items()
                    if node.get("kind") == "field"
                    and node.get("domain") == focus_ref.domain
                    and node.get("name") == focus_ref.name
                    and node.get("version") == focus_ref.version
                ),
            }
        )
    elif projection_version_id in builder.nodes:
        focus_kind = "projection"
        seed_ids.update(
            {
                projection_node_id,
                projection_version_id,
                *(
                    node_id
                    for node_id, node in builder.nodes.items()
                    if node.get("kind") == "projection_field"
                    and node.get("domain") == focus_ref.domain
                    and node.get("name") == focus_ref.name
                    and node.get("version") == focus_ref.version
                ),
            }
        )
    else:
        raise LookupError(f"unknown model or projection {focus_ref.domain}.{focus_ref.name}@{focus_ref.version}")

    selected = set(seed_ids)
    changed = True
    while changed:
        changed = False

        for child_id in list(selected):
            for parent_id in builder.parents.get(child_id, ()):
                if parent_id not in selected:
                    selected.add(parent_id)
                    changed = True

        if focus_kind == "model":
            selected.update(_projection_neighbors_for_model_focus(builder, selected))
        else:
            selected.update(_source_neighbors_for_projection_focus(builder, selected))

    return selected


def _projection_neighbors_for_model_focus(builder: _GraphBuilder, selected_ids: set[str]) -> set[str]:
    selected_fields = {node_id for node_id in selected_ids if builder.nodes[node_id]["kind"] == "field"}
    related: set[str] = set()
    for field_id in selected_fields:
        for edge in builder.edges_by_target.get(field_id, ()):
            if edge["kind"] != "maps_to":
                continue
            related.add(edge["source"])
            related.add(edge["target"])
    return related


def _source_neighbors_for_projection_focus(builder: _GraphBuilder, selected_ids: set[str]) -> set[str]:
    selected_projection_fields = {
        node_id for node_id in selected_ids if builder.nodes[node_id]["kind"] == "projection_field"
    }
    related: set[str] = set()
    for field_id in selected_projection_fields:
        for edge in builder.edges_by_source.get(field_id, ()):
            if edge["kind"] != "maps_to":
                continue
            related.add(edge["source"])
            related.add(edge["target"])
    return related


def _resolve_named_model_ref(workspace: Workspace, current_domain: str, type_name: str) -> Any:
    if "." in type_name:
        return resolve_model_ref(workspace.mdl, type_name, VersionMin(min_inclusive=0))
    candidates = [current_domain, *(domain.name for domain in workspace.mdl.domains if domain.name != current_domain)]
    for domain_name in candidates:
        try:
            return resolve_model_ref(workspace.mdl, f"{domain_name}.{type_name}", VersionMin(min_inclusive=0))
        except LookupError:
            continue
    raise LookupError(f"unknown model '{type_name}'")
