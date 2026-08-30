from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.registry.usage import build_usage_graph, build_usage_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def test_usage_graph_contains_exact_model_signatures() -> None:
    graph = build_usage_graph(load_workspace(FIXTURE))

    models = [node for node in graph["nodes"] if node["kind"] == "model_version"]

    assert graph["kind"] == "usage_graph"
    assert graph["application"] == "workspace"
    assert [node["target_ref"] for node in models] == ["customer.Customer@1", "customer.Customer@2"]
    assert all(len(node["signature"]) == 64 for node in models)


def test_usage_graph_connects_application_to_compiled_contract_versions() -> None:
    graph = build_usage_graph(load_workspace(FIXTURE))

    consumed = {
        edge["target"]
        for edge in graph["edges"]
        if edge["kind"] == "consumes" and edge["source"] == "application:workspace"
    }

    assert consumed == {
        "model_version:customer.Customer@1",
        "model_version:customer.Customer@2",
    }


def test_usage_manifest_is_compact() -> None:
    manifest = build_usage_manifest(load_workspace(FIXTURE))

    assert manifest["$schema"] == "modelable.usage/v0"
    assert manifest["kind"] == "usage_manifest"
    assert all(set(reference) == {"ref", "signature", "fields"} for reference in manifest["references"])


def test_usage_manifest_records_canonical_fields_for_each_contract() -> None:
    manifest = build_usage_manifest(load_workspace(FIXTURE))

    customer_v2 = next(reference for reference in manifest["references"] if reference["ref"] == "customer.Customer@2")

    assert customer_v2["fields"] == [
        "customer.Customer@2#createdAt",
        "customer.Customer@2#customerId",
        "customer.Customer@2#email",
        "customer.Customer@2#legalName",
        "customer.Customer@2#status",
    ]


def test_usage_cli_emits_json() -> None:
    result = CliRunner().invoke(cli, ["registry", "usage", str(FIXTURE), "--format", "manifest"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["$schema"] == "modelable.usage/v0"
    assert payload["kind"] == "usage_manifest"


def test_usage_manifest_includes_projection_signatures(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
  }
  projection CustomerView @ 1 from customer.Customer @ 1 as c {
    customerId <- c.customerId
  }
}
""".strip(),
        encoding="utf-8",
    )

    manifest = build_usage_manifest(load_workspace(source))

    assert [reference["ref"] for reference in manifest["references"]] == [
        "customer.Customer@1",
        "customer.CustomerView@1",
    ]
    assert all(len(reference["signature"]) == 64 for reference in manifest["references"])
    assert manifest["references"][0]["fields"] == ["customer.Customer@1#customerId"]


def test_usage_manifest_includes_enum_projection_contracts(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
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

    workspace = load_workspace(source)
    graph = build_usage_graph(workspace)
    manifest = build_usage_manifest(workspace)

    assert {
        "kind": "consumes",
        "source": "application:workspace",
        "target": "enum_projection:orders.PublicOrderStatus@1",
    } in graph["edges"]
    reference = next(item for item in manifest["references"] if item["ref"] == "orders.PublicOrderStatus@1")
    assert len(reference["signature"]) == 64
    assert reference["fields"] == []


def test_usage_graph_links_event_projections_to_their_source_models(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
  }
  auto projections Customer @ 1 {
    event on [created, updated]
  }
}
""".strip(),
        encoding="utf-8",
    )

    graph = build_usage_graph(load_workspace(source))

    assert {
        "kind": "emits",
        "source": "model_version:customer.Customer@1",
        "target": "projection_version:customer.CustomerEvent@1",
    } in graph["edges"]


def test_usage_graph_links_computed_projection_fields_to_dependencies(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    status: string
  }
  projection CustomerView @ 1 from customer.Customer @ 1 as c {
    isActive = c.status == "active"
  }
}
""".strip(),
        encoding="utf-8",
    )

    graph = build_usage_graph(load_workspace(source))

    assert {
        "kind": "field_depends_on",
        "source": "projection_field:customer.CustomerView@1#isActive",
        "target": "field:customer.Customer@1#status",
    } in graph["edges"]
