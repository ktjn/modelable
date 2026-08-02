from __future__ import annotations

import os
from pathlib import Path

import pytest

from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    ClarificationPlan,
    ConversationPlan,
    QueryPlan,
    UnsupportedPlan,
)
from modelable.llm.conversation_planner import (
    ConversationPlanner,
    PendingPlanRequest,
    PlannerContext,
    ResumableConversationPlanner,
)
from modelable.llm.providers import OllamaProvider, list_ollama_models
from modelable.llm.workspace_editor import WorkspaceEditError, WorkspaceEditor

pytestmark = pytest.mark.ollama

WORKSPACE = """\
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
domain billing {
  owner: "billing-team"
}
"""


def _provider() -> OllamaProvider:
    if os.environ.get("MODELABLE_OLLAMA_TESTS") != "1":
        pytest.skip("set MODELABLE_OLLAMA_TESTS=1 to run local Ollama conformance")
    model = os.environ.get("MODELABLE_OLLAMA_MODEL")
    if not model:
        pytest.fail("MODELABLE_OLLAMA_MODEL is required when Ollama conformance is enabled")
    return OllamaProvider(
        base_url=os.environ.get("MODELABLE_LLM_BASE_URL", "http://127.0.0.1:11434"),
        model=model,
    )


def _context() -> PlannerContext:
    return PlannerContext(
        workspace_summary=WORKSPACE,
        focused_ref="customer.Customer@1",
        history=(),
        pending_plan=None,
    )


def test_list_ollama_models_includes_conformance_model():
    if os.environ.get("MODELABLE_OLLAMA_TESTS") != "1":
        pytest.skip("set MODELABLE_OLLAMA_TESTS=1 to run local Ollama conformance")
    model = os.environ.get("MODELABLE_OLLAMA_MODEL")
    if not model:
        pytest.fail("MODELABLE_OLLAMA_MODEL is required when Ollama conformance is enabled")
    base_url = os.environ.get("MODELABLE_LLM_BASE_URL", "http://127.0.0.1:11434")
    names = list_ollama_models(base_url)
    assert model in names


@pytest.mark.parametrize(
    ("message", "expected_type"),
    [
        ("Describe the workspace", QueryPlan),
        (
            "Create billing.Invoice with a UUID invoiceId key and decimal total. "
            "Ownership is billing-team and identity is invoiceId.",
            ChangeSetPlan,
        ),
        (
            "Create a billing projection named CustomerProjection from customer.Customer@1, "
            "mapping customerId and name directly.",
            ChangeSetPlan,
        ),
        ("Add an optional email string field to customer.Customer@1 by appending version 2.", ChangeSetPlan),
        ("Create a projection, but I have not chosen its source or consumer domain.", ClarificationPlan),
    ],
)
def test_ollama_returns_valid_typed_conversation_plans(
    tmp_path: Path,
    message: str,
    expected_type: type[ConversationPlan],
) -> None:
    plan = ConversationPlanner(_provider()).plan(message, _context())

    if isinstance(plan, UnsupportedPlan):
        assert "valid typed plan" in plan.reason
        return
    assert isinstance(plan, expected_type), plan
    if isinstance(plan, ChangeSetPlan):
        source = tmp_path / "workspace.mdl"
        source.write_text(WORKSPACE, encoding="utf-8")
        try:
            preview = WorkspaceEditor(tmp_path).preview(plan)
        except WorkspaceEditError as error:
            assert str(error)
            return
        assert preview.candidate_sources
        assert not [diagnostic for diagnostic in preview.diagnostics if diagnostic.severity == "error"]
        assert all(text.count("{") == text.count("}") for text in preview.candidate_sources.values())


def test_ollama_can_complete_a_bounded_repair_request() -> None:
    provider = _provider()
    planner = ResumableConversationPlanner(repair_attempts=1)
    initial = planner.begin("Create billing.Invoice with invoiceId as its UUID key.", _context())
    assert isinstance(initial, PendingPlanRequest)
    repair = planner.resume(initial.request_id, "{malformed")
    assert isinstance(repair, PendingPlanRequest)

    response = provider.complete(repair.request)
    repaired = planner.resume(repair.request_id, response.content)

    assert isinstance(repaired, ChangeSetPlan), repaired
