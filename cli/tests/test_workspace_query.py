from __future__ import annotations

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.llm.conversation_plan import QueryPlan
from modelable.llm.qa import answer_question
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

domain analytics {
  owner: "analytics-team"

  projection CustomerAnalytics @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
  }
}

domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
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


def test_executes_all_remaining_query_kinds(query_service: WorkspaceQueryService) -> None:
    assert (
        "domain customer"
        in query_service.execute(QueryPlan(query_kind="summary", refs=[], question="Summarize the workspace")).text
    )
    assert (
        "customer.Customer@1"
        in query_service.execute(
            QueryPlan(query_kind="summary", refs=["customer.Customer@1"], question="Describe it")
        ).text
    )
    assert (
        "customer.Customer@1.customerId"
        in query_service.execute(
            QueryPlan(
                query_kind="lineage",
                refs=["billing.BillingCustomer@1"],
                question="Show its lineage",
            )
        ).text
    )
    assert (
        "no diagnostics"
        in query_service.execute(QueryPlan(query_kind="validation", refs=[], question="Is the workspace valid?")).text
    )


def test_dependents_are_rendered_in_deterministic_order(query_service: WorkspaceQueryService) -> None:
    text = query_service.execute(
        QueryPlan(
            query_kind="dependents",
            refs=["customer.Customer@1"],
            question="What depends on it?",
        )
    ).text

    assert text.index("analytics.CustomerAnalytics@1") < text.index("billing.BillingCustomer@1")


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


def test_malformed_reference_is_actionable(query_service: WorkspaceQueryService) -> None:
    result = query_service.execute(QueryPlan(query_kind="ownership", refs=["not-a-ref"], question="Who owns it?"))

    assert "Invalid reference" in result.text
    assert "domain.Model@version" in result.text


@pytest.mark.parametrize(
    ("query_kind", "ref", "expected"),
    [
        ("lineage", "customer.Customer@1", "require a projection reference"),
        ("dependents", "billing.BillingCustomer@1", "require a model reference"),
        ("indexes", "billing.BillingCustomer@1", "require a model reference"),
    ],
)
def test_wrong_definition_kind_is_actionable(
    query_service: WorkspaceQueryService,
    query_kind: str,
    ref: str,
    expected: str,
) -> None:
    plan = QueryPlan.model_validate({"kind": "query", "query_kind": query_kind, "refs": [ref], "question": "Tell me"})

    assert expected in query_service.execute(plan).text


def test_compatibility_projection_ref_reports_wrong_kind(query_service: WorkspaceQueryService) -> None:
    result = query_service.execute(
        QueryPlan(
            query_kind="compatibility",
            refs=["billing.BillingCustomer@1", "billing.BillingCustomer@1"],
            question="Is it compatible?",
        )
    )

    assert "requires model references" in result.text
    assert "billing.BillingCustomer@1 is a projection" in result.text


def test_compatibility_preserves_true_unknown_reference_error(query_service: WorkspaceQueryService) -> None:
    result = query_service.execute(
        QueryPlan(
            query_kind="compatibility",
            refs=["customer.Missing@1", "customer.Missing@2"],
            question="Is it compatible?",
        )
    )

    assert result.text == "Unknown model or projection reference: customer.Missing@1"


def test_cross_model_compatibility_is_rejected(query_service: WorkspaceQueryService) -> None:
    result = query_service.execute(
        QueryPlan(
            query_kind="compatibility",
            refs=["customer.Customer@1", "orders.Order@1"],
            question="Are these compatible?",
        )
    )

    assert "two versions of the same model" in result.text


@pytest.mark.parametrize(
    ("question", "plan"),
    [
        (
            "Who owns customer.Customer@1?",
            QueryPlan(query_kind="ownership", refs=["customer.Customer@1"], question="ignored"),
        ),
        (
            "What depends on customer.Customer@1?",
            QueryPlan(query_kind="dependents", refs=["customer.Customer@1"], question="ignored"),
        ),
        (
            "How can I look it up with an index customer.Customer@1?",
            QueryPlan(query_kind="indexes", refs=["customer.Customer@1"], question="ignored"),
        ),
        (
            "Describe model customer.Customer@1",
            QueryPlan(query_kind="summary", refs=["customer.Customer@1"], question="ignored"),
        ),
        (
            "Show lineage for billing.BillingCustomer@1",
            QueryPlan(query_kind="lineage", refs=["billing.BillingCustomer@1"], question="ignored"),
        ),
        (
            "Are there validation diagnostics?",
            QueryPlan(query_kind="validation", refs=[], question="ignored"),
        ),
    ],
)
def test_legacy_qa_matches_typed_query_facts(
    query_service: WorkspaceQueryService,
    question: str,
    plan: QueryPlan,
) -> None:
    expected = query_service.execute(plan).text

    assert answer_question(query_service.workspace, question) == expected
