import json

import pytest

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import dispatch_browser_request

GOVERNANCE_SOURCE = (
    "domain customer {\n"
    '  owner: "team"\n'
    "  entity Customer @ 1 (additive) {\n"
    "    @key customerId: uuid\n"
    "    @pii\n"
    "    email: string\n"
    "  }\n"
    "\n"
    "  projection CustomerView @ 1\n"
    "    from customer.Customer @ 1 as c\n"
    "  {\n"
    "    customerId <- c.customerId\n"
    "    contactEmail <- c.email\n"
    "  }\n"
    "}\n"
)
URI = "file:///customer.mdl"
SOURCES = [{"uri": URI, "text": GOVERNANCE_SOURCE, "version": 1}]

NO_PROJECTION_SOURCE = (
    "domain customer {\n"
    '  owner: "team"\n'
    "  entity Customer @ 1 (additive) {\n"
    "    @key customerId: uuid\n"
    "  }\n"
    "}\n"
)


@pytest.fixture(autouse=True)
def reset_browser_dispatch():
    browser_dispatch._reset_compiler_for_tests()


def dispatch(method, payload):
    return json.loads(dispatch_browser_request(method, json.dumps(payload)))


def open_workspace(revision=100, sources=SOURCES):
    result = dispatch("workspace.open", {"workspaceRevision": revision, "sources": sources})
    assert result["ok"]
    return result


def test_governance_returns_findings():
    open_workspace()
    result = dispatch("workspace.governance", {"workspaceRevision": 100})

    assert result["ok"]
    r = result["result"]
    assert r["workspace_revision"] == 100
    assert len(r["findings"]) > 0

    codes = {f["code"] for f in r["findings"]}
    assert "missing_project_grant" in codes or "missing_pii_metadata" in codes


def test_governance_findings_have_required_fields():
    open_workspace()
    result = dispatch("workspace.governance", {"workspaceRevision": 100})

    for finding in result["result"]["findings"]:
        assert "code" in finding
        assert "subject" in finding
        assert "message" in finding
        assert isinstance(finding["code"], str)
        assert isinstance(finding["subject"], str)
        assert isinstance(finding["message"], str)


def test_governance_no_projections_returns_empty():
    open_workspace(sources=[{"uri": URI, "text": NO_PROJECTION_SOURCE, "version": 1}])
    result = dispatch("workspace.governance", {"workspaceRevision": 100})

    assert result["ok"]
    assert result["result"]["findings"] == []


def test_governance_rejects_stale_workspace():
    open_workspace(50)
    result = dispatch("workspace.governance", {"workspaceRevision": 49})

    assert not result["ok"]
    assert result["error"]["code"] == "STALE_WORKSPACE"


def test_governance_rejects_extra_fields():
    open_workspace()
    result = dispatch("workspace.governance", {"workspaceRevision": 100, "extra": True})

    assert not result["ok"]
    assert result["error"]["code"] == "INVALID_REQUEST"
