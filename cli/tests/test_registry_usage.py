from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.registry.usage import aggregate_usage_graph, build_usage_graph, build_usage_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def test_usage_graph_contains_exact_model_signatures() -> None:
    graph = build_usage_graph(load_workspace(FIXTURE))

    models = [node for node in graph["nodes"] if node["kind"] == "model_version"]

    assert graph["kind"] == "usage_graph"
    assert graph["application"] == "workspace"
    assert [node["target_ref"] for node in models] == ["customer.Customer@1", "customer.Customer@2"]
    assert all(len(node["signature"]) == 64 for node in models)


def test_usage_evidence_exposes_stable_application_and_package_ids(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
workspace "billing-service" {
  package "api" {
    include: ["billing"]
  }
}
domain billing {
  entity Invoice @ 1 (additive) {
    @key
    invoiceId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )

    graph = build_usage_graph(load_workspace(source))
    manifest = build_usage_manifest(load_workspace(source))

    assert graph["application"] == "billing-service"
    assert graph["application_id"] == "application:billing-service"
    assert graph["packages"] == [{"id": "package:billing-service/api", "name": "api"}]
    assert {
        "kind": "consumes",
        "source": "package:billing-service/api",
        "target": "model_version:billing.Invoice@1",
    } in graph["edges"]
    assert manifest["application_id"] == "application:billing-service"
    assert manifest["packages"] == [{"id": "package:billing-service/api", "name": "api"}]
    assert manifest["references"][0]["package_id"] == "package:billing-service/api"


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


def test_usage_cli_aggregates_compiled_consumer_manifests(tmp_path: Path) -> None:
    workspace = load_workspace(FIXTURE)
    manifests = []
    for application in ("billing-web", "analytics-worker"):
        manifest = build_usage_manifest(workspace)
        manifest["application"] = application
        manifest["application_id"] = f"application:{application}"
        path = tmp_path / f"{application}.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        manifests.append(path)

    args = ["registry", "usage", str(FIXTURE), "--format", "json"]
    for path in manifests:
        args.extend(["--usage-manifest", str(path)])

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    applications = [node["id"] for node in payload["nodes"] if node["kind"] == "application"]
    assert applications == ["application:analytics-worker", "application:billing-web", "application:workspace"]
    assert {
        (edge["source"], edge["target"])
        for edge in payload["edges"]
        if edge["kind"] == "consumes" and edge["source"] != "application:workspace"
    } == {
        ("application:analytics-worker", "model_version:customer.Customer@1"),
        ("application:analytics-worker", "model_version:customer.Customer@2"),
        ("application:billing-web", "model_version:customer.Customer@1"),
        ("application:billing-web", "model_version:customer.Customer@2"),
    }


def test_usage_aggregation_ignores_stale_compiled_signatures() -> None:
    workspace = load_workspace(FIXTURE)
    manifest = build_usage_manifest(workspace)
    manifest["application"] = "stale-consumer"
    manifest["application_id"] = "application:stale-consumer"
    manifest["references"][0]["signature"] = "0" * 64

    graph = aggregate_usage_graph(workspace, [manifest])

    assert {
        (edge["source"], edge["target"])
        for edge in graph["edges"]
        if edge["kind"] == "consumes" and edge["source"] == "application:stale-consumer"
    } == {
        ("application:stale-consumer", "model_version:customer.Customer@2"),
    }


def test_usage_cli_includes_explicit_artifact_manifest(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )
    artifact_manifest = tmp_path / "modelable-artifact-manifest.json"
    artifact_manifest.write_text(
        json.dumps(
            {
                "format": "modelable.artifact-manifest.v1",
                "target": {"name": "typescript"},
                "artifacts": [{"path": "customer.Customer.v1.ts", "ref": "customer.Customer@1", "sha256": "c" * 64}],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["registry", "usage", str(source), "--format", "manifest", "--artifact-manifest", str(artifact_manifest)],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["artifacts"] == [
        {
            "path": "customer.Customer.v1.ts",
            "ref": "customer.Customer@1",
            "sha256": "c" * 64,
            "target": "typescript",
        }
    ]


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


def test_usage_manifest_includes_application_surface_declarations(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
  }
  projection CustomerReply @ 1 from customer.Customer @ 1 as c {
    customerId <- c.customerId
  }
  auto projections Customer @ 1 {
    event on [created, updated]
  }
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
}
binding customerStore {
  adapter: postgres
  model: customer.Customer @ 1
  table: "customers"
}
""".strip(),
        encoding="utf-8",
    )

    manifest = build_usage_manifest(load_workspace(source))

    assert manifest["surfaces"] == [
        {
            "id": "api_operation:customer.Customer@1:getCustomer",
            "kind": "api_operation",
            "method": "GET",
            "name": "getCustomer",
            "path": "/customers/{id}",
            "ref": "customer.Customer@1",
        },
        {
            "id": "event:customer.CustomerEvent@1",
            "kind": "event",
            "operations": ["created", "updated"],
            "ref": "customer.CustomerEvent@1",
        },
        {
            "adapter": "postgres",
            "id": "storage:postgres:customers",
            "kind": "storage",
            "ref": "customer.Customer@1",
            "table": "customers",
        },
    ]


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


def test_usage_graph_declares_generated_artifacts_and_manifest_preserves_them(tmp_path: Path) -> None:
    source = tmp_path / "models.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )
    artifact_manifest = {
        "format": "modelable.artifact-manifest.v1",
        "target": {"name": "typescript", "kind": "language", "status": "implemented"},
        "artifacts": [{"path": "customer.Customer.v1.ts", "ref": "customer.Customer@1", "sha256": "a" * 64}],
    }

    workspace = load_workspace(source)
    graph = build_usage_graph(workspace, artifact_manifests=(artifact_manifest,))
    manifest = build_usage_manifest(workspace, artifact_manifests=(artifact_manifest,))

    assert {
        "kind": "generated_from",
        "source": "generated_artifact:typescript/customer.Customer.v1.ts",
        "target": "model_version:customer.Customer@1",
    } in graph["edges"]
    assert {
        "id": "generated_artifact:typescript/customer.Customer.v1.ts",
        "kind": "generated_artifact",
        "label": "customer.Customer.v1.ts",
        "path": "customer.Customer.v1.ts",
        "ref": "customer.Customer@1",
        "sha256": "a" * 64,
        "target": "typescript",
    } in graph["nodes"]
    assert manifest["artifacts"] == [
        {
            "path": "customer.Customer.v1.ts",
            "ref": "customer.Customer@1",
            "sha256": "a" * 64,
            "target": "typescript",
        }
    ]
