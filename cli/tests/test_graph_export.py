from __future__ import annotations

import json
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.graph.export import build_graph_export


def test_graph_export_includes_models_projections_and_mappings(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    displayName = c.name
  }
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    graph = build_graph_export(workspace)

    assert graph["kind"] == "workspace_graph"
    assert [node["kind"] for node in graph["nodes"]] == [
        "domain",
        "model",
        "model_version",
        "field",
        "field",
        "projection",
        "projection_version",
        "projection_field",
        "projection_field",
    ]
    assert [edge["kind"] for edge in graph["edges"]] == [
        "owns",
        "version_of",
        "contains_field",
        "contains_field",
        "has_projection",
        "version_of_projection",
        "contains_field",
        "contains_field",
        "maps_to",
    ]
    assert any(edge["kind"] == "maps_to" for edge in graph["edges"])


def test_graph_export_is_deterministic(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    first = json.dumps(build_graph_export(workspace), sort_keys=True)
    second = json.dumps(build_graph_export(workspace), sort_keys=True)

    assert first == second


def test_graph_export_focuses_on_projection_and_source_fields(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    displayName = c.name
  }
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    graph = build_graph_export(workspace, focus="customer.CustomerView@1")

    assert [node["kind"] for node in graph["nodes"]] == [
        "domain",
        "model",
        "model_version",
        "field",
        "projection",
        "projection_version",
        "projection_field",
        "projection_field",
    ]
    assert graph["nodes"][3]["field"] == "customerId"
    assert any(edge["kind"] == "maps_to" for edge in graph["edges"])
