from __future__ import annotations

from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.dependency_graph import build_projection_dependencies
from modelable.graph.export import build_graph_export
from modelable.identity import declaration_id
from modelable.registry.signature import compute_enum_projection_signature, compute_version_signature

USAGE_SCHEMA = "modelable.usage/v0"


def build_usage_graph(workspace: Workspace) -> dict[str, Any]:
    """Build the cross-surface usage graph for a validated workspace.

    The existing semantic graph supplies model, field, projection, and lineage
    nodes. This layer adds application-facing consumers so impact analysis can
    evolve without changing the stable semantic graph format.
    """
    graph = build_graph_export(workspace)
    nodes = list(graph["nodes"])
    edges = list(graph["edges"])
    node_ids = {node["id"] for node in nodes}
    edge_keys = {(edge["kind"], edge["source"], edge["target"]) for edge in edges}

    application_name = _application_name(workspace)
    application_id = f"application:{application_name}"
    packages = _package_identities(workspace, application_id)
    package_by_domain = _package_ids_by_domain(workspace, application_id)
    _add_node(
        nodes,
        node_ids,
        {"id": application_id, "kind": "application", "label": application_name, "name": application_name},
    )
    for node in nodes:
        if node["kind"] in {"model_version", "projection_version", "enum_projection"}:
            _add_edge(edges, edge_keys, "consumes", application_id, node["id"])
            domain_name = str(node.get("target_ref", "")).split(".", 1)[0]
            package_id = package_by_domain.get(domain_name)
            if package_id is not None:
                _add_edge(edges, edge_keys, "consumes", package_id, node["id"])

    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for projection in versions:
                projection_id = "projection_version:" + declaration_id(domain.name, projection_name, projection.version)
                source_ref = _resolve_source_ref(workspace, projection.source.model, projection.source.version)
                source_id = f"model_version:{source_ref}"
                _add_edge(edges, edge_keys, "projects_from", projection_id, source_id)
                if projection.event_operations:
                    _add_edge(edges, edge_keys, "emits", source_id, projection_id)
                consumer_ref = declaration_id(domain.name, projection_name, projection.version)
                for dependency in build_projection_dependencies(
                    workspace.mdl,
                    domain.name,
                    projection_name,
                    projection,
                ):
                    if dependency.usage_kind == "direct":
                        continue
                    dependency_source = (
                        f"projection_field:{consumer_ref}#{dependency.target_property}"
                        if dependency.target_property is not None
                        else f"projection_version:{consumer_ref}"
                    )
                    dependency_target = f"field:{dependency.source_ref}#{dependency.source_property}"
                    _add_edge(edges, edge_keys, "field_depends_on", dependency_source, dependency_target)

        for api in domain.apis:
            for api_version in [api.version]:
                for operation in api.operations:
                    operation_id = f"api_operation:{domain.name}.{api.model}@{api_version}:{operation.name}"
                    _add_node(
                        nodes,
                        node_ids,
                        {
                            "id": operation_id,
                            "kind": "api_operation",
                            "label": operation.name,
                            "domain": domain.name,
                            "model": api.model,
                            "version": api_version,
                            "method": operation.method,
                            "path": operation.path,
                            "target_ref": declaration_id(domain.name, api.model, api_version),
                        },
                    )
                    _add_edge(edges, edge_keys, "exposes", application_id, operation_id)
                    if operation.request is not None:
                        request_id = _projection_id(domain.name, *operation.request)
                        _add_edge(edges, edge_keys, "request_body", operation_id, request_id)
                    for response in operation.responses:
                        response_id = _projection_id(domain.name, response.projection, response.version)
                        _add_edge(edges, edge_keys, "responds_with", operation_id, response_id)

        for binding in workspace.mdl.bindings:
            storage_id = f"storage:{binding.adapter}:{binding.table or binding.name}"
            _add_node(
                nodes,
                node_ids,
                {
                    "id": storage_id,
                    "kind": "storage",
                    "label": binding.table or binding.name,
                    "adapter": binding.adapter,
                    "table": binding.table,
                },
            )
            model_id = f"model_version:{binding.model}@{binding.model_version}"
            _add_edge(edges, edge_keys, "persists_as", model_id, storage_id)

    for node in nodes:
        if node["kind"] == "model_version":
            domain_name, rest = str(node["target_ref"]).split(".", 1)
            model_name, version = rest.rsplit("@", 1)
            model_version = next(
                version_item
                for item in workspace.mdl.domains
                if item.name == domain_name
                for version_item in item.models.get(model_name, [])
                if version_item.version == int(version)
            )
            node["signature"] = compute_version_signature(domain_name, model_name, model_version)
        elif node["kind"] == "projection_version":
            domain_name, rest = str(node["target_ref"]).split(".", 1)
            projection_name, version = rest.rsplit("@", 1)
            projection_version = next(
                version_item
                for item in workspace.mdl.domains
                if item.name == domain_name
                for version_item in item.projections.get(projection_name, [])
                if version_item.version == int(version)
            )
            node["signature"] = compute_version_signature(domain_name, projection_name, projection_version)
        elif node["kind"] == "enum_projection":
            domain_name, rest = str(node["target_ref"]).split(".", 1)
            projection_name, version = rest.rsplit("@", 1)
            enum_projection = next(
                projection
                for item in workspace.mdl.domains
                if item.name == domain_name
                for projection in item.enum_projections
                if projection.name == projection_name and projection.version == int(version)
            )
            node["signature"] = compute_enum_projection_signature(domain_name, enum_projection)

    return {
        "kind": "usage_graph",
        "application": application_name,
        "application_id": application_id,
        "packages": packages,
        "nodes": sorted(nodes, key=lambda item: (item["kind"], item["id"])),
        "edges": sorted(edges, key=lambda item: (item["kind"], item["source"], item["target"])),
    }


def build_usage_manifest(workspace: Workspace) -> dict[str, Any]:
    graph = build_usage_graph(workspace)
    nodes = {node["id"]: node for node in graph["nodes"]}
    fields_by_version: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        if edge["kind"] != "contains_field":
            continue
        field = nodes.get(edge["target"])
        if field is not None and field["kind"] in {"field", "projection_field"}:
            fields_by_version.setdefault(edge["source"], []).append(str(field["target_ref"]))

    references = []
    package_by_domain = _package_ids_by_domain(workspace, str(graph["application_id"]))
    for node in graph["nodes"]:
        if node["kind"] not in {"model_version", "projection_version", "enum_projection"}:
            continue
        reference = {
            "ref": node["target_ref"],
            "signature": node["signature"],
            "fields": sorted(fields_by_version.get(node["id"], [])),
        }
        domain_name = str(node["target_ref"]).split(".", 1)[0]
        package_id = package_by_domain.get(domain_name)
        if package_id is not None:
            reference["package_id"] = package_id
        references.append(reference)
    return {
        "$schema": USAGE_SCHEMA,
        "kind": "usage_manifest",
        "application": graph["application"],
        "application_id": graph["application_id"],
        "packages": graph["packages"],
        "references": references,
    }


def _application_name(workspace: Workspace) -> str:
    if workspace.mdl.workspace is not None:
        configured = workspace.mdl.workspace.name or workspace.mdl.workspace.label
        if configured:
            return configured
    return "workspace"


def _package_identities(workspace: Workspace, application_id: str) -> list[dict[str, str]]:
    if workspace.mdl.workspace is None:
        return []
    return [
        {"id": f"package:{application_id.removeprefix('application:')}/{package.name}", "name": package.name}
        for package in sorted(workspace.mdl.workspace.packages, key=lambda item: item.name)
    ]


def _package_ids_by_domain(workspace: Workspace, application_id: str) -> dict[str, str]:
    if workspace.mdl.workspace is None:
        return {}
    application_name = application_id.removeprefix("application:")
    return {
        domain_name: f"package:{application_name}/{package.name}"
        for package in workspace.mdl.workspace.packages
        for domain_name in package.include
    }


def _resolve_source_ref(workspace: Workspace, model: str, version_spec: Any) -> str:
    from modelable.registry.resolver import resolve_model_ref

    resolved = resolve_model_ref(workspace.mdl, model, version_spec)
    return declaration_id(resolved.domain_name, resolved.model_name, resolved.version.version)


def _projection_id(domain: str, projection: str, version: int) -> str:
    return "projection_version:" + declaration_id(domain, projection, version)


def _add_node(nodes: list[dict[str, Any]], node_ids: set[str], node: dict[str, Any]) -> None:
    if node["id"] not in node_ids:
        nodes.append(node)
        node_ids.add(node["id"])


def _add_edge(
    edges: list[dict[str, Any]],
    edge_keys: set[tuple[str, str, str]],
    kind: str,
    source: str,
    target: str,
) -> None:
    key = (kind, source, target)
    if key not in edge_keys:
        edges.append({"kind": kind, "source": source, "target": target})
        edge_keys.add(key)
