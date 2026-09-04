from __future__ import annotations

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.planner.plans import build_plan_documents


def test_plan_v1_projects_normalized_facets_without_overlay_metadata() -> None:
    """Bypassing normalized workspace facets would lose typed facts or leak target overlay fields."""
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="memory://facet-plan.mdl",
                text="""
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key id: uuid
    customerId: string
  }
  projection OrderView @ 1
    from orders.Order @ 1 as order
  {
    customerId <- order.customerId
  }
}
""",
            )
        ],
        facets_document={
            "$schema": "modelable.facets/v1",
            "schemas": [
                {
                    "identity": "org.example/jurisdiction@1",
                    "value_schema": {"type": "string"},
                    "allowed_subjects": ["declaration", "field"],
                    "propagation": "inherit",
                },
                {
                    "identity": "org.example/retention-class@1",
                    "value_schema": {"type": "string", "enum": ["regulated"]},
                    "allowed_subjects": ["field", "projection_field"],
                    "propagation": "project",
                },
            ],
            "facets": [
                {
                    "identity": "org.example/jurisdiction@1",
                    "value": "SE",
                    "subject": "declaration:orders.Order@1",
                    "propagation": "inherit",
                },
                {
                    "identity": "org.example/retention-class@1",
                    "value": "regulated",
                    "subject": "field:orders.Order@1#customerId",
                    "propagation": "project",
                },
            ],
        },
    )
    assert workspace.errors == []

    plan = build_plan_documents(workspace)[0]
    source = plan["source"]
    source_customer_id = source["resolved"]["fields"][1]
    projected_customer_id = plan["fields"][0]

    assert [facet["identity"] for facet in source["facets"]] == ["org.example/jurisdiction@1"]
    assert [facet["identity"] for facet in source_customer_id["facets"]] == [
        "org.example/jurisdiction@1",
        "org.example/retention-class@1",
    ]
    assert [facet["identity"] for facet in projected_customer_id["facets"]] == [
        "org.example/retention-class@1",
    ]
    assert all(
        set(facet) <= {"identity", "value", "subject", "propagation", "source", "interpretation"}
        for facet in projected_customer_id["facets"]
    )
