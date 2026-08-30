from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modelable.consequence_protocol import CONSEQUENCE_SCHEMA, validate_consequence_graph

ACTION_NO_ACTION = "no_action"
ACTION_RECOMPILE = "recompile"
ACTION_REGENERATE = "regenerate"
ACTION_CONSUMER_UPDATE = "consumer_update"
ACTION_BREAKING = "breaking"


@dataclass(frozen=True)
class Consequence:
    action: str
    subject: str
    status: str
    reason: str | None = None
    causal_path: tuple[str, ...] = ()
    causal_changes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "subject": self.subject,
            "status": self.status,
            "reason": self.reason,
            "causal_path": list(self.causal_path),
        }


def build_consequence_graph(
    consequences: list[Consequence], change_nodes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Build a deterministic node/edge view from consequence causal paths."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()
    for change_node in change_nodes or []:
        nodes[change_node["id"]] = change_node
    for consequence in consequences:
        path = consequence.causal_path or (consequence.subject,)
        for reference in path:
            nodes.setdefault("reference:" + reference, {"id": reference, "kind": "reference", "label": reference})
        edges.update(("causes", path[index], path[index + 1]) for index in range(len(path) - 1))
        action_id = f"action:{consequence.action}:{consequence.subject}"
        nodes[action_id] = {
            "id": action_id,
            "kind": "action",
            "label": consequence.action,
            "action": consequence.action,
            "subject": consequence.subject,
            "status": consequence.status,
        }
        for change_id in consequence.causal_changes:
            edges.add(("causes", path[0], change_id))
            edges.add(("causes", change_id, path[-1]))
        edges.add(("requires", path[-1], action_id))
    graph = {
        "$schema": CONSEQUENCE_SCHEMA,
        "kind": "consequence_graph",
        "nodes": sorted(nodes.values(), key=lambda node: str(node["id"])),
        "edges": [{"kind": kind, "source": source, "target": target} for kind, source, target in sorted(edges)],
    }
    return validate_consequence_graph(graph)


def action_for_projection_status(status: str) -> str:
    if status == "broken":
        return ACTION_BREAKING
    if status == "affected":
        return ACTION_REGENERATE
    return ACTION_NO_ACTION
