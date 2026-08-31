from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.consequence_protocol import validate_consequence_graph
from modelable.registry.snapshot import resolve_workspace_snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def test_impact_json_reports_projection_consequences(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    email: string
  }
  entity Customer @ 2 (breaking) {
    @key
    customerId: uuid
  }
}
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1 from customer.Customer @ 1 as c {
    id <- c.customerId
    emailAddress <- c.email
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["kind"] == "consequence_report"
    assert payload["status"] == "breaking"
    assert any(item["action"] == "breaking" for item in payload["consequences"])
    assert any("billing.BillingCustomer@1" in item["causal_path"] for item in payload["consequences"])
    graph = payload["consequence_graph"]
    assert validate_consequence_graph(graph) == graph
    assert graph["$schema"] == "modelable.consequence/v0"
    assert graph["kind"] == "consequence_graph"
    assert {node["id"] for node in graph["nodes"]} >= {
        "customer.Customer@1",
        "customer.Customer@2",
        "billing.BillingCustomer@1",
    }
    assert {
        "kind": "causes",
        "source": "customer.Customer@1",
        "target": "customer.Customer@2",
    } in graph["edges"]
    assert {
        "kind": "causes",
        "source": "customer.Customer@1",
        "target": "billing.BillingCustomer@1",
    } in graph["edges"]
    change_node = next(node for node in graph["nodes"] if node["id"] == "change:removed_field:email")
    assert change_node["kind"] == "change"
    assert change_node["field"] == "email"
    assert change_node["change_kind"] == "removed_field"
    assert {
        "kind": "causes",
        "source": "customer.Customer@1",
        "target": "change:removed_field:email",
    } in graph["edges"]
    assert {
        "kind": "causes",
        "source": "change:removed_field:email",
        "target": "billing.BillingCustomer@1",
    } in graph["edges"]


def test_impact_json_reports_projection_governance_review(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key
    orderId: uuid
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    access {
      entity orders [read, project]
    }
    orderId <- o.orderId
  }
  projection OrderView @ 2 from orders.Order @ 1 as o {
    access {
      entity orders [read, project]
      entity analytics [read]
    }
    orderId <- o.orderId
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "orders.OrderView@1",
            "--to",
            "orders.OrderView@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {
        "action": "governance_review",
        "causal_path": [
            "orders.OrderView@1",
            "orders.OrderView@2",
            "governance-review:orders.OrderView:access_grant_added",
        ],
        "reason": "access grant added: entity principal 'analytics' permission 'read'",
        "status": "review_required",
        "subject": "governance-review:orders.OrderView:access_grant_added",
    } in payload["consequences"]
    assert validate_consequence_graph(payload["consequence_graph"]) == payload["consequence_graph"]


def test_impact_json_reports_projection_wire_consequence(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key
    orderId: int
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    @wire(rust.type: "u32")
    orderId <- o.orderId
  }
  projection OrderView @ 2 from orders.Order @ 1 as o {
    @wire(rust.type: "u64")
    orderId <- o.orderId
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "orders.OrderView@1",
            "--to",
            "orders.OrderView@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert {
        "action": "breaking",
        "causal_path": [
            "orders.OrderView@1",
            "orders.OrderView@2",
            "wire:orders.OrderView:wire_hint_changed",
        ],
        "reason": "field 'orderId' @wire hint for 'rust' changed",
        "status": "breaking",
        "subject": "wire:orders.OrderView:wire_hint_changed",
    } in payload["consequences"]
    assert validate_consequence_graph(payload["consequence_graph"]) == payload["consequence_graph"]


def test_impact_json_reports_data_backfill_for_defaulted_required_field(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    id: uuid
    name: string
  }
  entity Customer @ 2 (breaking) {
    @key
    id: uuid
    name: string
    status: string = "active"
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert {
        "action": "data_backfill",
        "causal_path": [
            "customer.Customer@1",
            "customer.Customer@2",
            "data-backfill:customer.Customer:field_added_with_default",
        ],
        "reason": "field 'status' has a default and requires a data backfill",
        "status": "migration_required",
        "subject": "data-backfill:customer.Customer:field_added_with_default",
    } in payload["consequences"]
    assert validate_consequence_graph(payload["consequence_graph"]) == payload["consequence_graph"]


def test_impact_json_reports_enum_exhaustive_consumer_review(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders-team"
  semantic Status @ 1 (additive): enum(active, blocked)
  semantic Status @ 2 (additive): enum(active, blocked, deleted)
  entity Order @ 1 (additive) {
    @key
    orderId: uuid
    status: Status @ 1
  }
  entity Order @ 2 (breaking) {
    @key
    orderId: uuid
    status: Status @ 2
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "orders.Order@1",
            "--to",
            "orders.Order@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {
        "action": "consumer_update",
        "causal_path": [
            "orders.Order@1",
            "orders.Order@2",
            "enum-exhaustive-match:orders.Order:status",
        ],
        "reason": "Status@2: adds member 'deleted' (exhaustive consumers must extend their handling)",
        "status": "review_required",
        "subject": "enum-exhaustive-match:orders.Order:status",
    } in payload["consequences"]
    assert validate_consequence_graph(payload["consequence_graph"]) == payload["consequence_graph"]


def test_impact_json_reports_source_consequence_for_added_optional_field(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    id: uuid
    name: string
  }
  entity Customer @ 2 (additive) {
    @key
    id: uuid
    name: string
    nickname?: string
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert {
        "action": "recompile",
        "causal_path": [
            "customer.Customer@1",
            "customer.Customer@2",
            "source:customer.Customer:added_field",
        ],
        "reason": "added_field nickname",
        "status": "compatible",
        "subject": "source:customer.Customer:added_field",
    } in payload["consequences"]
    assert validate_consequence_graph(payload["consequence_graph"]) == payload["consequence_graph"]


def test_impact_can_load_dependents_from_an_offline_snapshot(tmp_path: Path) -> None:
    provider = tmp_path / "provider.mdl"
    provider.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    email: string
  }
}
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1 from customer.Customer @ 1 as c {
    id <- c.customerId
    emailAddress <- c.email
  }
}
""".strip(),
        encoding="utf-8",
    )
    snapshot = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(provider), snapshot)

    candidate = tmp_path / "candidate.mdl"
    candidate.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 2 (breaking) {
    @key
    customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(candidate),
            "--snapshot",
            str(snapshot),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert any("billing.BillingCustomer@1" in item["causal_path"] for item in payload["consequences"])


def test_impact_includes_known_consumers_from_usage_manifest(tmp_path: Path) -> None:
    source = tmp_path / "candidate.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    email: string
  }
  entity Customer @ 2 (breaking) {
    @key
    customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )
    manifest = tmp_path / "billing-usage.json"
    manifest.write_text(
        json.dumps(
            {
                "$schema": "modelable.usage/v0",
                "kind": "usage_manifest",
                "application": "billing-service",
                "application_id": "application:billing-service",
                "packages": [{"id": "package:billing-service/api", "name": "api"}],
                "references": [
                    {
                        "ref": "customer.Customer@1",
                        "signature": "a" * 64,
                        "fields": ["customer.Customer@1#email"],
                        "package_id": "package:billing-service/api",
                    }
                ],
                "artifacts": [
                    {
                        "path": "customer.Customer.v1.ts",
                        "ref": "customer.Customer@1",
                        "sha256": "b" * 64,
                        "target": "typescript",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(source),
            "--usage-manifest",
            str(manifest),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert {
        "action": "consumer_update",
        "subject": "package:billing-service/api",
        "status": "breaking",
        "reason": "compiled usage manifest",
        "causal_path": ["customer.Customer@1", "customer.Customer@2", "package:billing-service/api"],
    } in payload["consequences"]
    assert {
        "action": "regenerate",
        "subject": "generated_artifact:typescript/customer.Customer.v1.ts",
        "status": "breaking",
        "reason": "generated artifact requires regeneration",
        "causal_path": [
            "customer.Customer@1",
            "customer.Customer@2",
            "generated_artifact:typescript/customer.Customer.v1.ts",
        ],
    } in payload["consequences"]

    text_result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(source),
            "--usage-manifest",
            str(manifest),
        ],
    )
    assert text_result.exit_code == 1, text_result.output
    assert "consumer_update: package:billing-service/api (compiled usage manifest)" in text_result.output


def test_impact_graph_omits_nonbreaking_changes(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "customer.Customer@1",
            "--to",
            "customer.Customer@2",
            "--path",
            str(FIXTURE),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert not any(node["kind"] == "change" for node in payload["consequence_graph"]["nodes"])


def test_impact_graph_includes_storage_migration_consequence(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
  entity Order @ 2 (additive) {
    @key orderId: uuid
  }
  index Order @ 2 {
    primary orderId
    secondary by_order {
      key: [orderId]
    }
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "billing.Order@1",
            "--to",
            "billing.Order@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any(item["action"] == "storage_migration" for item in payload["consequences"])
    graph = validate_consequence_graph(payload["consequence_graph"])
    assert any(node["action"] == "storage_migration" for node in graph["nodes"] if node["kind"] == "action")
    assert any(node["id"] == "change:index_changed:by_order" for node in graph["nodes"])


def test_impact_graph_includes_projection_rebuild_consequence(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain orders {
  owner: "orders"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: string
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    orderId <- o.orderId
    isShipped = o.status == "shipped"
  }
  projection OrderView @ 2 from orders.Order @ 1 as o {
    orderId <- o.orderId
    isShipped = o.status == "delivered"
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "impact",
            "--from",
            "orders.OrderView@1",
            "--to",
            "orders.OrderView@2",
            "--path",
            str(source),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any(item["action"] == "projection_rebuild" for item in payload["consequences"])
    graph = validate_consequence_graph(payload["consequence_graph"])
    assert any(node["action"] == "projection_rebuild" for node in graph["nodes"] if node["kind"] == "action")
