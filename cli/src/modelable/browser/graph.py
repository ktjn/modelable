from __future__ import annotations

from typing import Any

from modelable.browser.dto import (
    BrowserGraph,
    BrowserGraphEdge,
    BrowserGraphNode,
    BrowserGraphResult,
)
from modelable.compiler.workspace import Workspace
from modelable.graph.export import build_graph_export

_NODE_KIND_MAP: dict[str, str] = {
    "domain": "domain",
    "model": "entity",
    "model_version": "version",
    "field": "field",
    "projection": "projection",
    "projection_version": "version",
    "projection_field": "field",
}

_EDGE_KIND_MAP: dict[str, str] = {
    "owns": "contains",
    "version_of": "contains",
    "contains_field": "contains",
    "has_projection": "contains",
    "version_of_projection": "contains",
    "maps_to": "projects",
}

_DOMAIN_MODE_NODE_KINDS = {"domain", "entity", "projection"}


def build_browser_graph(
    workspace: Workspace,
    mode: str,
    workspace_revision: int,
) -> BrowserGraphResult:
    raw = build_graph_export(workspace)
    nodes = _convert_nodes(raw.get("nodes", []))
    edges = _convert_edges(raw.get("edges", []))

    if mode == "domain":
        node_ids = {node.id for node in nodes if node.kind in _DOMAIN_MODE_NODE_KINDS}
        nodes = tuple(node for node in nodes if node.id in node_ids)
        edges = tuple(edge for edge in edges if edge.source in node_ids and edge.target in node_ids)

    return BrowserGraphResult(
        workspace_revision=workspace_revision,
        mode=mode,
        graph=BrowserGraph(
            schema_version=1,
            nodes=nodes,
            edges=edges,
        ),
    )


def _convert_nodes(
    raw_nodes: list[dict[str, Any]],
) -> tuple[BrowserGraphNode, ...]:
    return tuple(_convert_node(node) for node in raw_nodes)


def _convert_node(raw: dict[str, Any]) -> BrowserGraphNode:
    kind = _NODE_KIND_MAP.get(raw["kind"], raw["kind"])
    metadata: dict[str, Any] = {}
    for key in (
        "domain",
        "name",
        "version",
        "change_kind",
        "model_kind",
        "optional",
        "field",
        "source_ref",
        "mapping_kind",
    ):
        if key in raw:
            metadata[key] = raw[key]
    return BrowserGraphNode(
        id=raw["id"],
        kind=kind,
        label=raw.get("label", ""),
        metadata=metadata,
        source_range=None,
    )


def _convert_edges(
    raw_edges: list[dict[str, Any]],
) -> tuple[BrowserGraphEdge, ...]:
    return tuple(_convert_edge(edge) for edge in raw_edges)


def _convert_edge(raw: dict[str, Any]) -> BrowserGraphEdge:
    kind = _EDGE_KIND_MAP.get(raw["kind"], raw["kind"])
    return BrowserGraphEdge(
        id=f"{kind}:{raw['source']}->{raw['target']}",
        source=raw["source"],
        target=raw["target"],
        kind=kind,
    )
