from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.dependency_graph import build_projection_dependencies
from modelable.graph.export import build_graph_export
from modelable.identity import declaration_id, parse_declaration_id
from modelable.registry.signature import compute_enum_projection_signature, compute_version_signature

USAGE_SCHEMA = "modelable.usage/v0"


def build_usage_graph(
    workspace: Workspace,
    *,
    artifact_manifests: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
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

    artifacts = _artifact_declarations(artifact_manifests)
    node_by_ref = {
        str(node["target_ref"]): str(node["id"])
        for node in nodes
        if node.get("kind") in {"model_version", "projection_version", "enum_projection"} and "target_ref" in node
    }
    for artifact in artifacts:
        artifact_id = _artifact_node_id(artifact)
        _add_node(
            nodes,
            node_ids,
            {
                "id": artifact_id,
                "kind": "generated_artifact",
                "label": artifact["path"],
                "path": artifact["path"],
                "ref": artifact.get("ref"),
                "sha256": artifact["sha256"],
                "target": artifact["target"],
            },
        )
        ref = artifact.get("ref")
        target_id = node_by_ref.get(ref) if isinstance(ref, str) else None
        if target_id is not None:
            _add_edge(edges, edge_keys, "generated_from", artifact_id, target_id)

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


def aggregate_usage_graph(
    workspace: Workspace,
    usage_manifests: Sequence[Mapping[str, Any]],
    *,
    artifact_manifests: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Add exact compiled-consumer evidence to a workspace usage graph."""
    graph = build_usage_graph(workspace, artifact_manifests=artifact_manifests)
    nodes = list(graph["nodes"])
    edges = list(graph["edges"])
    node_ids = {str(node["id"]) for node in nodes}
    edge_keys = {(edge["kind"], edge["source"], edge["target"]) for edge in edges}
    contracts = {
        str(node["target_ref"]): node
        for node in nodes
        if node.get("kind") in {"model_version", "projection_version", "enum_projection"}
    }

    for manifest in usage_manifests:
        application = manifest.get("application")
        if not isinstance(application, str):
            continue
        application_id = manifest.get("application_id")
        if not isinstance(application_id, str) or not application_id:
            application_id = f"application:{application}"
        _add_node(
            nodes,
            node_ids,
            {"id": application_id, "kind": "application", "label": application, "name": application},
        )
        package_ids: set[str] = set()
        packages = manifest.get("packages")
        if isinstance(packages, list):
            for package in packages:
                if not isinstance(package, Mapping):
                    continue
                package_id = package.get("id")
                package_name = package.get("name")
                if not isinstance(package_id, str) or not isinstance(package_name, str):
                    continue
                package_ids.add(package_id)
                _add_node(
                    nodes,
                    node_ids,
                    {"id": package_id, "kind": "package", "label": package_name, "name": package_name},
                )
        references = manifest.get("references")
        if not isinstance(references, list):
            continue
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            ref = reference.get("ref")
            signature = reference.get("signature")
            contract = contracts.get(ref) if isinstance(ref, str) else None
            if contract is None or contract.get("signature") != signature:
                continue
            target = str(contract["id"])
            _add_edge(edges, edge_keys, "consumes", application_id, target)
            package_id = reference.get("package_id")
            if isinstance(package_id, str) and package_id in package_ids:
                _add_edge(edges, edge_keys, "consumes", package_id, target)

    return {
        **graph,
        "nodes": sorted(nodes, key=lambda item: (item["kind"], item["id"])),
        "edges": sorted(edges, key=lambda item: (item["kind"], item["source"], item["target"])),
    }


def build_usage_manifest(
    workspace: Workspace,
    *,
    artifact_manifests: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    graph = build_usage_graph(workspace, artifact_manifests=artifact_manifests)
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
    event_operations = _event_operations_by_ref(workspace)
    payload: dict[str, Any] = {
        "$schema": USAGE_SCHEMA,
        "kind": "usage_manifest",
        "application": graph["application"],
        "application_id": graph["application_id"],
        "packages": graph["packages"],
        "references": references,
        "surfaces": _surface_declarations(graph, event_operations),
    }
    artifacts = _artifact_declarations(artifact_manifests)
    if artifacts:
        payload["artifacts"] = artifacts
    return payload


def _surface_declarations(graph: Mapping[str, Any], event_operations: Mapping[str, list[str]]) -> list[dict[str, Any]]:
    """Return compact declarations for application-facing graph surfaces."""
    nodes = {str(node["id"]): node for node in graph["nodes"]}
    surfaces: dict[str, dict[str, Any]] = {}
    for node in graph["nodes"]:
        if node.get("kind") == "api_operation":
            surfaces[str(node["id"])] = {
                "id": node["id"],
                "kind": "api_operation",
                "ref": node["target_ref"],
                "name": node["label"],
                "method": node["method"],
                "path": node["path"],
            }

    for edge in graph["edges"]:
        if edge["kind"] == "emits":
            target = nodes.get(str(edge["target"]))
            if target is not None and target.get("kind") == "projection_version":
                ref = target.get("target_ref")
                if isinstance(ref, str):
                    surface_id = f"event:{ref}"
                    surfaces[surface_id] = {
                        "id": surface_id,
                        "kind": "event",
                        "ref": ref,
                        "operations": event_operations[ref],
                    }
        elif edge["kind"] == "persists_as":
            source = nodes.get(str(edge["source"]))
            target = nodes.get(str(edge["target"]))
            if source is None or target is None or source.get("kind") != "model_version":
                continue
            ref = source.get("target_ref")
            if not isinstance(ref, str):
                continue
            surface_id = str(target["id"])
            surface = {
                "id": surface_id,
                "kind": "storage",
                "ref": ref,
                "adapter": target["adapter"],
            }
            if target.get("table") is not None:
                surface["table"] = target["table"]
            surfaces[surface_id] = surface
    return [surfaces[key] for key in sorted(surfaces)]


def _event_operations_by_ref(workspace: Workspace) -> dict[str, list[str]]:
    return {
        declaration_id(domain.name, projection_name, projection.version): list(projection.event_operations)
        for domain in workspace.mdl.domains
        for projection_name, versions in domain.projections.items()
        for projection in versions
        if projection.event_operations
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


def _artifact_declarations(manifests: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    declarations: dict[tuple[str, str], dict[str, str]] = {}
    for manifest in manifests:
        target = manifest.get("target")
        target_name = target.get("name") if isinstance(target, Mapping) else None
        entries = manifest.get("artifacts")
        if not isinstance(target_name, str) or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            path = entry.get("path")
            sha256 = entry.get("sha256")
            if not isinstance(path, str) or not path or not isinstance(sha256, str) or not sha256:
                continue
            ref = entry.get("ref")
            declaration = {
                "path": path,
                "sha256": sha256,
                "target": target_name,
            }
            if isinstance(ref, str):
                try:
                    parse_declaration_id(ref)
                except ValueError:
                    pass
                else:
                    declaration["ref"] = ref
            declarations[(target_name, path)] = declaration
    return [declarations[key] for key in sorted(declarations)]


def _artifact_node_id(artifact: Mapping[str, str | None]) -> str:
    return f"generated_artifact:{artifact['target']}/{artifact['path']}"


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
