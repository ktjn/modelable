import json
from pathlib import Path

import pytest

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import BrowserCompiler, BrowserSource, dispatch_browser_request
from modelable.browser.errors import BrowserLanguageError
from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import serialize_plan

FIXTURE = Path(__file__).parent / "fixtures" / "multi_domain_joins.mdl"


def test_browser_plans_match_native_plan_documents() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    browser = BrowserCompiler()
    browser.open_workspace(1, (BrowserSource(uri="file:///models.mdl", text=text, version=1),))

    native_workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=FIXTURE, uri="file:///models.mdl", text=text)]
    )

    native_plans = tuple(serialize_plan(plan) for plan in build_plan_documents(native_workspace))
    assert browser.plans(1).plans == native_plans
    assert browser.plans(1).plans == native_plans


def test_browser_plan_dispatch_enforces_current_revision() -> None:
    browser = BrowserCompiler()
    browser.open_workspace(
        4,
        (BrowserSource(uri="file:///models.mdl", text=FIXTURE.read_text(encoding="utf-8"), version=1),),
    )

    result = browser.plans(4)

    assert result.workspace_revision == 4
    assert [json.loads(plan)["$schema"] for plan in result.plans] == ["modelable.plan/v0"]

    with pytest.raises(BrowserLanguageError, match="STALE_WORKSPACE"):
        browser.plans(3)


def test_browser_plan_dispatch_returns_json_protocol_result() -> None:
    browser_dispatch._reset_compiler_for_tests()
    text = FIXTURE.read_text(encoding="utf-8")
    opened = dispatch_browser_request(
        "workspace.open",
        json.dumps({"workspaceRevision": 6, "sources": [{"uri": "file:///models.mdl", "text": text, "version": 1}]}),
    )
    assert json.loads(opened)["ok"] is True

    response = json.loads(dispatch_browser_request("workspace.plans", '{"workspaceRevision":6}'))

    assert response["ok"] is True
    assert response["result"]["workspace_revision"] == 6
    assert '"$schema":"modelable.plan/v0"' in response["result"]["plans"][0]
    assert json.loads(dispatch_browser_request("workspace.plans", '{"workspaceRevision":6,"extra":true}')) == {
        "ok": False,
        "error": {"code": "INVALID_REQUEST", "message": "Payload does not match method schema"},
    }
