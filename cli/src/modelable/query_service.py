"""In-process read-only service for ``modelable.query/v1``."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from modelable.compat.checker import check_model_version_compatibility
from modelable.compiler.workspace import Workspace
from modelable.consequence import build_model_consequences
from modelable.graph.export import build_graph_export
from modelable.lifecycle import parse_lifecycle_document
from modelable.llm.context import parse_model_ref
from modelable.migration import migration_edges, parse_migration_document
from modelable.query_protocol import QUERY_SCHEMA, validate_query_request
from modelable.registry.usage_protocol import validate_usage_manifest

_RELATION_KINDS = frozenset({"references", "maps_to", "projects_from"})


class WorkspaceQueryProtocolService:
    """Answer deterministic query/v1 requests from one validated workspace."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        usage_manifests: Sequence[Mapping[str, Any]] = (),
        lifecycle: Mapping[str, Any] | None = None,
        migration: Mapping[str, Any] | None = None,
    ) -> None:
        self.workspace = workspace
        self.usage_manifests = tuple(validate_usage_manifest(manifest) for manifest in usage_manifests)
        self.lifecycle = parse_lifecycle_document(lifecycle) if lifecycle is not None else None
        self.migration = parse_migration_document(migration) if migration is not None else None

    def execute(self, request: object) -> dict[str, Any]:
        normalized = validate_query_request(request)
        query = str(normalized["query"])
        ref = str(normalized.get("id"))
        if query in {"changes", "consequences"}:
            data = self._compatibility_query(normalized, include_consequences=query == "consequences")
        elif query == "lifecycle":
            data = self._lifecycle_query(ref)
        else:
            graph = self._graph_with_migrations()
            data = self._graph_query(graph, query, ref)
        response: dict[str, Any] = {"$schema": QUERY_SCHEMA, "kind": "query_result", "query": query}
        if query not in {"changes", "consequences", "lifecycle"}:
            data, next_cursor = self._paginate_graph(
                data,
                query=query,
                ref=ref,
                limit=int(normalized["limit"]),
                cursor=normalized.get("cursor"),
            )
            response["data"] = data
            if next_cursor is not None:
                response["next_cursor"] = next_cursor
        else:
            response["data"] = data
        return response

    def _graph_with_migrations(self) -> dict[str, Any]:
        graph = build_graph_export(self.workspace)
        if self.migration is None:
            return graph
        nodes = list(graph["nodes"])
        edges = list(graph["edges"])
        known = {str(node["id"]) for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), str)}
        for edge in migration_edges(self.migration):
            source_id = f"migration:{edge['source']}"
            target_id = f"migration:{edge['target']}"
            for node_id, reference in ((source_id, edge["source"]), (target_id, edge["target"])):
                if node_id not in known:
                    nodes.append(
                        {"id": node_id, "kind": "migration_reference", "label": reference, "target_ref": reference}
                    )
                    known.add(node_id)
            edges.append(
                {
                    "kind": "migrates_to",
                    "source": source_id,
                    "target": target_id,
                    "mapping_kind": edge["kind"],
                    "immediate": edge["immediate"],
                    "ultimate": edge["ultimate"],
                    "ultimate_sources": edge["ultimate_sources"],
                }
            )
        return {**graph, "nodes": nodes, "edges": edges}

    def _lifecycle_query(self, ref: str | None) -> dict[str, Any]:
        if ref is None:
            raise ValueError("query family 'lifecycle' requires an id")
        if self.lifecycle is None:
            raise ValueError("lifecycle metadata was not supplied")
        entry = next((item for item in self.lifecycle["entries"] if item["identity"] == ref), None)
        if entry is None:
            raise ValueError(f"lifecycle metadata not found for {ref}")
        return dict(entry)

    def _graph_query(self, graph: Mapping[str, Any], query: str, ref: str | None) -> dict[str, Any]:
        if ref is None:
            raise ValueError(f"query family {query!r} requires an id")
        nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
        edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
        selected_ids = {
            str(node["id"]) for node in nodes if isinstance(node.get("id"), str) and node.get("target_ref") == ref
        }
        if not selected_ids:
            raise ValueError(f"query reference not found: {ref}")
        if query == "declaration":
            selected_nodes = [node for node in nodes if node.get("id") in selected_ids]
            return {"nodes": selected_nodes, "edges": []}
        if query == "lineage":
            relation_edges = [
                edge
                for edge in edges
                if edge.get("kind") in {"maps_to", "migrates_to"}
                and (edge.get("source") in selected_ids or edge.get("target") in selected_ids)
            ]
        elif query == "consumersOf":
            relation_edges = self._usage_consumer_edges(nodes, selected_ids, ref)
        elif query in {"referencesTo", "dependents"} or query == "dependencies":
            relation_edges = self._relation_edges(nodes, edges, selected_ids, query)
        else:
            raise ValueError(f"unsupported graph query family: {query!r}")
        related_ids = selected_ids | {
            str(endpoint)
            for edge in relation_edges
            for endpoint in (edge.get("source"), edge.get("target"))
            if isinstance(endpoint, str)
        }
        selected_nodes = [node for node in nodes if node.get("id") in related_ids]
        known_node_ids = {str(node["id"]) for node in selected_nodes if isinstance(node.get("id"), str)}
        for edge in relation_edges:
            source = edge.get("source")
            if not isinstance(source, str) or source in known_node_ids:
                continue
            if source.startswith("application:"):
                kind = "application"
            elif source.startswith("package:"):
                kind = "package"
            else:
                continue
            label = source.split(":", 1)[1]
            selected_nodes.append({"id": source, "kind": kind, "label": label, "name": label})
        selected_nodes.sort(key=lambda node: (str(node.get("kind", "")), str(node.get("id", ""))))
        return {"nodes": selected_nodes, "edges": relation_edges}

    def _relation_edges(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], selected_ids: set[str], query: str
    ) -> list[dict[str, str]]:
        relation_edges = [
            edge
            for edge in edges
            if edge.get("kind") in _RELATION_KINDS
            and isinstance(edge.get("source"), str)
            and isinstance(edge.get("target"), str)
        ]
        model_edges = [
            {
                "kind": "projects_from",
                "source": str(node["id"]),
                "target": f"model_version:{node['source_ref']}",
            }
            for node in nodes
            if isinstance(node.get("id"), str)
            and node.get("kind") == "projection_version"
            and isinstance(node.get("source_ref"), str)
        ]
        relation_edges.extend(model_edges)
        if query in {"referencesTo", "consumersOf", "dependents"}:
            filtered = [edge for edge in relation_edges if edge["target"] in selected_ids]
        else:
            filtered = [edge for edge in relation_edges if edge["source"] in selected_ids]
        if query == "dependents" or query == "consumersOf":
            filtered = [edge for edge in relation_edges if edge["target"] in selected_ids]
        return sorted(filtered, key=lambda edge: (edge["kind"], edge["source"], edge["target"]))

    def _usage_consumer_edges(
        self, nodes: list[dict[str, Any]], selected_ids: set[str], ref: str | None
    ) -> list[dict[str, str]]:
        if ref is None:
            return []
        target_by_ref = {
            str(node["target_ref"]): str(node["id"])
            for node in nodes
            if isinstance(node.get("id"), str) and isinstance(node.get("target_ref"), str)
        }
        edges: set[tuple[str, str, str]] = set()
        for manifest in self.usage_manifests:
            application = manifest.get("application_id") or manifest.get("application")
            if not isinstance(application, str) or not application:
                continue
            references = manifest.get("references")
            if not isinstance(references, list):
                continue
            packages = manifest.get("packages")
            package_ids = (
                {
                    str(package["id"])
                    for package in packages
                    if isinstance(package, Mapping) and isinstance(package.get("id"), str)
                }
                if isinstance(packages, list)
                else set()
            )
            for reference in references:
                if not isinstance(reference, Mapping):
                    continue
                declaration_ref = reference.get("ref")
                fields = reference.get("fields")
                matches = declaration_ref == ref or (isinstance(fields, list) and ref in fields)
                target = target_by_ref.get(ref) if matches else None
                if target is None or target not in selected_ids:
                    continue
                edges.add(("consumes", application, target))
                package_id = reference.get("package_id")
                if isinstance(package_id, str) and package_id in package_ids:
                    edges.add(("consumes", package_id, target))
        return [{"kind": kind, "source": source, "target": target} for kind, source, target in sorted(edges)]

    def _compatibility_query(self, request: Mapping[str, Any], *, include_consequences: bool) -> dict[str, Any]:
        try:
            old = parse_model_ref(str(request["from"]))
            new = parse_model_ref(str(request["to"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("changes and consequences require domain.Model@version references") from exc
        if (old.domain, old.name) != (new.domain, new.name):
            raise ValueError("changes and consequences require two versions of the same model")
        report = check_model_version_compatibility(self.workspace.mdl, old.domain, old.name, old.version, new.version)
        data: dict[str, Any] = {
            "from": str(request["from"]),
            "to": str(request["to"]),
            "status": report.status,
            "findings": list(report.findings),
        }
        if include_consequences:
            data["consequences"] = [item.as_dict() for item in build_model_consequences(self.workspace, report)]
        return data

    @staticmethod
    def _paginate_graph(
        data: dict[str, Any], *, query: str, ref: str, limit: int, cursor: object
    ) -> tuple[dict[str, Any], str | None]:
        nodes = list(data.get("nodes", []))
        edges = list(data.get("edges", []))
        fingerprint = _graph_fingerprint(query, ref, nodes, edges)
        edge_offset = _decode_cursor(cursor, query=query, ref=ref, fingerprint=fingerprint)
        if not edges:
            return {"nodes": nodes, "edges": []}, None
        page_edges = edges[edge_offset : edge_offset + limit]
        page_node_ids = {
            endpoint
            for edge in page_edges
            for endpoint in (edge.get("source"), edge.get("target"))
            if isinstance(endpoint, str)
        }
        page_nodes = [node for node in nodes if node.get("id") in page_node_ids]
        next_edge_offset = edge_offset + len(page_edges)
        next_cursor = (
            _encode_cursor(query, ref, fingerprint, next_edge_offset) if next_edge_offset < len(edges) else None
        )
        return {"nodes": page_nodes, "edges": page_edges}, next_cursor


def _graph_fingerprint(query: str, ref: str, nodes: list[Any], edges: list[Any]) -> str:
    payload = json.dumps(
        {"query": query, "id": ref, "nodes": nodes, "edges": edges},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _encode_cursor(query: str, ref: str, fingerprint: str, edge_offset: int) -> str:
    payload = json.dumps(
        {"v": 1, "query": query, "id": ref, "fingerprint": fingerprint, "edge": edge_offset},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: object, *, query: str, ref: str, fingerprint: str) -> int:
    if cursor is None:
        return 0
    if not isinstance(cursor, str):
        raise ValueError("query cursor must be a valid query/v1 cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("query cursor must be a valid query/v1 cursor") from error
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("query") != query
        or payload.get("id") != ref
        or payload.get("fingerprint") != fingerprint
        or not isinstance(payload.get("edge"), int)
        or isinstance(payload.get("edge"), bool)
        or payload["edge"] < 0
    ):
        raise ValueError("query cursor does not match this query")
    return cast(int, payload["edge"])
