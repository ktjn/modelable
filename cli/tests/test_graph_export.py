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


def test_graph_export_links_ref_fields_to_target_model_versions(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  entity Address @ 1 (additive) {
    @key addressId: uuid
  }
}

domain sales {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customer: ref<customer.Customer @ 1>
    addresses: array<ref<customer.Address @ 1>>
  }
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    graph = build_graph_export(workspace)

    assert {
        "kind": "references",
        "source": "field:sales.Order@1#customer",
        "target": "model_version:customer.Customer@1",
    } in graph["edges"]
    assert {
        "kind": "references",
        "source": "field:sales.Order@1#addresses",
        "target": "model_version:customer.Address@1",
    } in graph["edges"]


def test_graph_export_links_named_fields_to_semantic_type_versions(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  semantic CustomerId @ 1 (additive): string
  entity Customer @ 1 (additive) {
    @key
    customerId: CustomerId
  }
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    graph = build_graph_export(workspace)

    assert any(
        node["id"] == "semantic_type:customer.CustomerId@1" and node["kind"] == "semantic_type"
        for node in graph["nodes"]
    )
    assert {
        "kind": "owns",
        "source": "domain:customer",
        "target": "semantic_type:customer.CustomerId@1",
    } in graph["edges"]
    assert {
        "kind": "references",
        "source": "field:customer.Customer@1#customerId",
        "target": "semantic_type:customer.CustomerId@1",
    } in graph["edges"]


def test_graph_export_links_named_fields_to_value_model_versions(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    billingAddress?: Address
  }
  value Address @ 1 (additive) {
    street: string
  }
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    graph = build_graph_export(workspace)

    assert {
        "kind": "references",
        "source": "field:customer.Customer@1#billingAddress",
        "target": "model_version:customer.Address@1",
    } in graph["edges"]


def test_graph_export_links_enum_projections_to_semantic_sources(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(draft, approved)
  enum projection PublicOrderStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(approved)
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    graph = build_graph_export(workspace)

    assert {
        "id": "enum_projection:orders.PublicOrderStatus@1",
        "kind": "enum_projection",
        "label": "PublicOrderStatus@1",
        "domain": "orders",
        "name": "PublicOrderStatus",
        "version": 1,
        "source_ref": "orders.OrderStatus@1",
        "target_ref": "orders.PublicOrderStatus@1",
    } in graph["nodes"]
    assert {
        "kind": "has_projection",
        "source": "domain:orders",
        "target": "enum_projection:orders.PublicOrderStatus@1",
    } in graph["edges"]
    assert {
        "kind": "projects_from",
        "source": "enum_projection:orders.PublicOrderStatus@1",
        "target": "semantic_type:orders.OrderStatus@1",
    } in graph["edges"]


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
