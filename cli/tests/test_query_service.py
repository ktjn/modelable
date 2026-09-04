from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.query_service import WorkspaceQueryProtocolService
from modelable.registry.usage import build_usage_manifest


def _workspace(tmp_path: Path):
    (tmp_path / "workspace.mdl").write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
  projection CustomerView @ 1 from customer.Customer @ 1 as c {
    customerId <- c.customerId
    name <- c.name
  }
}
""".strip(),
        encoding="utf-8",
    )
    return load_workspace(tmp_path)


def _faceted_workspace(tmp_path: Path):
    _workspace(tmp_path)
    (tmp_path / "modelable.facets.json").write_text(
        """
{
  "$schema": "modelable.facets/v1",
  "schemas": [
    {
      "identity": "org.example/retention-class@1",
      "value_schema": {"type": "string"},
      "allowed_subjects": ["field", "projection_field"],
      "propagation": "project"
    },
    {
      "identity": "org.example/jurisdiction@1",
      "value_schema": {"type": "string"},
      "allowed_subjects": ["declaration", "field"],
      "propagation": "inherit"
    }
  ],
  "facets": [
    {
      "identity": "org.example/retention-class@1",
      "value": "regulated",
      "subject": "field:customer.Customer@1#name",
      "propagation": "project"
    },
    {
      "identity": "org.example/jurisdiction@1",
      "value": "SE",
      "subject": "declaration:customer.Customer@1",
      "propagation": "inherit"
    },
    {
      "identity": "org.example/future-fact@1",
      "value": {"rank": 2},
      "subject": "field:customer.Customer@1#name",
      "propagation": "none"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    return load_workspace(tmp_path)


def test_query_service_exposes_normalized_facets_with_deterministic_pagination(tmp_path: Path) -> None:
    service = WorkspaceQueryProtocolService(_faceted_workspace(tmp_path))
    request = {
        "$schema": "modelable.query/v1",
        "kind": "query",
        "query": "facets",
        "id": "customer.Customer@1#name",
        "limit": 2,
    }

    first = service.execute(request)
    second = service.execute({**request, "cursor": first["next_cursor"]})

    assert [facet["identity"] for facet in first["data"]["facets"]] == [
        "org.example/future-fact@1",
        "org.example/jurisdiction@1",
    ]
    assert first["data"]["facets"][0]["interpretation"] == "unknown"
    assert isinstance(first["next_cursor"], str)
    assert [facet["identity"] for facet in second["data"]["facets"]] == ["org.example/retention-class@1"]
    assert "next_cursor" not in second

    projected = service.execute(
        {
            "$schema": "modelable.query/v1",
            "kind": "query",
            "query": "facets",
            "id": "customer.CustomerView@1#name",
        }
    )
    assert projected["data"]["facets"] == [
        {
            "identity": "org.example/retention-class@1",
            "value": "regulated",
            "subject": "projection_field:customer.CustomerView@1#name",
            "propagation": "project",
            "source": {"subject": "field:customer.Customer@1#name"},
            "interpretation": "known",
        }
    ]


def test_declaration_query_exposes_facets_on_declarations_and_fields(tmp_path: Path) -> None:
    service = WorkspaceQueryProtocolService(_faceted_workspace(tmp_path))

    result = service.execute(
        {
            "$schema": "modelable.query/v1",
            "kind": "query",
            "query": "declaration",
            "id": "customer.Customer@1",
        }
    )

    nodes_by_ref = {node["target_ref"]: node for node in result["data"]["nodes"]}
    assert [facet["identity"] for facet in nodes_by_ref["customer.Customer@1"]["facets"]] == [
        "org.example/jurisdiction@1"
    ]

    lineage = service.execute(
        {
            "$schema": "modelable.query/v1",
            "kind": "query",
            "query": "lineage",
            "id": "customer.CustomerView@1#name",
        }
    )
    field_nodes_by_ref = {node["target_ref"]: node for node in lineage["data"]["nodes"]}
    assert [facet["identity"] for facet in field_nodes_by_ref["customer.Customer@1#name"]["facets"]] == [
        "org.example/future-fact@1",
        "org.example/jurisdiction@1",
        "org.example/retention-class@1",
    ]


def test_query_service_answers_declaration_and_dependents_deterministically(tmp_path: Path) -> None:
    service = WorkspaceQueryProtocolService(_workspace(tmp_path))

    declaration = service.execute(
        {"$schema": "modelable.query/v1", "kind": "query", "query": "declaration", "id": "customer.Customer@1"}
    )
    dependents = service.execute(
        {"$schema": "modelable.query/v1", "kind": "query", "query": "dependents", "id": "customer.Customer@1"}
    )

    assert declaration["data"]["nodes"][0]["target_ref"] == "customer.Customer@1"
    assert dependents["data"]["edges"] == [
        {
            "kind": "projects_from",
            "source": "projection_version:customer.CustomerView@1",
            "target": "model_version:customer.Customer@1",
        }
    ]


def test_query_service_answers_lifecycle_state_and_replacement(tmp_path: Path) -> None:
    lifecycle = {
        "$schema": "modelable.lifecycle/v1",
        "entries": [{"identity": "customer.Customer@1", "state": "deprecated", "replacement": "customer.Customer@2"}],
    }
    service = WorkspaceQueryProtocolService(_workspace(tmp_path), lifecycle=lifecycle)

    result = service.execute(
        {"$schema": "modelable.query/v1", "kind": "query", "query": "lifecycle", "id": "customer.Customer@1"}
    )

    assert result["data"] == {
        "identity": "customer.Customer@1",
        "state": "deprecated",
        "replacement": "customer.Customer@2",
    }


def test_query_service_answers_projection_lineage(tmp_path: Path) -> None:
    service = WorkspaceQueryProtocolService(_workspace(tmp_path))

    result = service.execute(
        {
            "$schema": "modelable.query/v1",
            "kind": "query",
            "query": "lineage",
            "id": "customer.CustomerView@1#name",
        }
    )

    assert result["data"]["edges"] == [
        {
            "kind": "maps_to",
            "source": "projection_field:customer.CustomerView@1#name",
            "target": "field:customer.Customer@1#name",
        }
    ]


def test_query_service_answers_explicit_migration_lineage(tmp_path: Path) -> None:
    migration = {
        "$schema": "modelable.migration/v1",
        "mappings": [{"kind": "rename", "sources": ["legacy.Customer@1"], "targets": ["customer.Customer@1"]}],
    }
    service = WorkspaceQueryProtocolService(_workspace(tmp_path), migration=migration)

    result = service.execute(
        {
            "$schema": "modelable.query/v1",
            "kind": "query",
            "query": "lineage",
            "id": "customer.Customer@1",
        }
    )

    assert result["data"]["edges"] == [
        {
            "kind": "migrates_to",
            "source": "migration:legacy.Customer@1",
            "target": "migration:customer.Customer@1",
            "mapping_kind": "rename",
            "immediate": "legacy.Customer@1",
            "ultimate": "legacy.Customer@1",
            "ultimate_sources": ["legacy.Customer@1"],
        }
    ]


def test_query_service_paginates_graph_results(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace.mdl"
    workspace_path.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) { @key customerId: uuid }
  projection CustomerView @ 1 from customer.Customer @ 1 as c { customerId <- c.customerId }
  projection CustomerSummary @ 1 from customer.Customer @ 1 as c { customerId <- c.customerId }
}
""".strip(),
        encoding="utf-8",
    )
    service = WorkspaceQueryProtocolService(load_workspace(tmp_path))
    request = {
        "$schema": "modelable.query/v1",
        "kind": "query",
        "query": "dependents",
        "id": "customer.Customer@1",
        "limit": 1,
    }

    first = service.execute(request)
    assert len(first["data"]["edges"]) == 1
    assert isinstance(first["next_cursor"], str)

    second = service.execute({**request, "cursor": first["next_cursor"]})
    assert len(second["data"]["edges"]) == 1
    assert second["data"]["edges"] != first["data"]["edges"]
    assert "next_cursor" not in second


def test_query_service_answers_usage_backed_consumers(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    usage_manifest = build_usage_manifest(workspace)
    service = WorkspaceQueryProtocolService(workspace, usage_manifests=[usage_manifest])

    result = service.execute(
        {
            "$schema": "modelable.query/v1",
            "kind": "query",
            "query": "consumersOf",
            "id": "customer.Customer@1#name",
        }
    )

    assert result["data"]["edges"] == [
        {
            "kind": "consumes",
            "source": "application:workspace",
            "target": "field:customer.Customer@1#name",
        }
    ]
    assert result["data"]["nodes"][0]["id"] == "application:workspace"
