from __future__ import annotations

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.llm.conversation_plan import QueryPlan
from modelable.llm.workspace_query import WorkspaceQueryService


@pytest.fixture
def query_service(tmp_path) -> WorkspaceQueryService:
    (tmp_path / "workspace.mdl").write_text(
        """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    email: string
  }

  entity Customer @ 2 (breaking) {
    @key customerId: uuid
  }

  index Customer @ 1 {
    primary customerId
    secondary byEmail {
      key: [email]
      unique: true
    }
  }
}

domain billing {
  owner: "billing-team"

  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    email <- c.email
  }
}
""",
        encoding="utf-8",
    )
    return WorkspaceQueryService(load_workspace(tmp_path))


def test_executes_grounded_workspace_queries(query_service: WorkspaceQueryService) -> None:
    assert (
        "customer-team"
        in query_service.execute(
            QueryPlan(kind="query", query_kind="ownership", refs=["customer.Customer@1"], question="Who owns it?")
        ).text
    )
    assert (
        "byEmail"
        in query_service.execute(
            QueryPlan(
                kind="query",
                query_kind="indexes",
                refs=["customer.Customer@1"],
                question="How can I look it up?",
            )
        ).text
    )
    assert (
        "billing.BillingCustomer@1"
        in query_service.execute(
            QueryPlan(
                kind="query",
                query_kind="dependents",
                refs=["customer.Customer@1"],
                question="What depends on it?",
            )
        ).text
    )
    assert (
        "breaking"
        in query_service.execute(
            QueryPlan(
                kind="query",
                query_kind="compatibility",
                refs=["customer.Customer@1", "customer.Customer@2"],
                question="Is v2 compatible?",
            )
        ).text
    )


@pytest.mark.parametrize(
    ("query_kind", "refs", "expected"),
    [
        ("summary", ["customer.Customer@1", "customer.Customer@2"], "exactly zero or one reference"),
        ("ownership", [], "exactly one reference"),
        ("lineage", [], "exactly one reference"),
        ("dependents", [], "exactly one reference"),
        ("indexes", [], "exactly one reference"),
        ("compatibility", ["customer.Customer@1"], "exactly two references"),
        ("validation", ["customer.Customer@1"], "exactly zero references"),
    ],
)
def test_rejects_invalid_reference_counts(
    query_service: WorkspaceQueryService,
    query_kind: str,
    refs: list[str],
    expected: str,
) -> None:
    plan = QueryPlan.model_validate({"kind": "query", "query_kind": query_kind, "refs": refs, "question": "Tell me"})

    result = query_service.execute(plan)

    assert expected in result.text
    assert result.refs == tuple(refs)


def test_unknown_reference_is_reported_without_guessing(query_service: WorkspaceQueryService) -> None:
    result = query_service.execute(
        QueryPlan(
            kind="query",
            query_kind="ownership",
            refs=["customer.Missing@1"],
            question="Who owns it?",
        )
    )

    assert result.text == "Unknown model or projection reference: customer.Missing@1"
    assert result.refs == ("customer.Missing@1",)
