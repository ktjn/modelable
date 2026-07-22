import json

import pytest

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import dispatch_browser_request

ANALYSIS_SOURCE = (
    "domain customer {\n"
    '  owner: "team"\n'
    "  entity Customer @ 1 (additive) {\n"
    "    @key customerId: uuid\n"
    "    name: string\n"
    "  }\n"
    "\n"
    "  entity Customer @ 2 (additive) {\n"
    "    @key customerId: uuid\n"
    "    name: string\n"
    "    @pii\n"
    "    email?: string\n"
    "  }\n"
    "\n"
    "  projection CustomerView @ 1\n"
    "    from customer.Customer @ 2 as c\n"
    "  {\n"
    "    customerId <- c.customerId\n"
    "    displayName <- c.name\n"
    "    isBillable = c.email != null\n"
    "  }\n"
    "}\n"
)
URI = "file:///customer.mdl"
SOURCES = [{"uri": URI, "text": ANALYSIS_SOURCE, "version": 1}]

EMPTY_SOURCE = 'domain empty {\n  owner: "team"\n}\n'


@pytest.fixture(autouse=True)
def reset_browser_dispatch():
    browser_dispatch._reset_compiler_for_tests()


def dispatch(method, payload):
    return json.loads(dispatch_browser_request(method, json.dumps(payload)))


def open_workspace(revision=100, sources=SOURCES):
    result = dispatch("workspace.open", {"workspaceRevision": revision, "sources": sources})
    assert result["ok"]
    return result


def test_lineage_returns_projection_fields():
    open_workspace()
    result = dispatch("workspace.lineage", {"workspaceRevision": 100})

    assert result["ok"]
    r = result["result"]
    assert r["workspace_revision"] == 100
    assert len(r["projections"]) == 1

    proj = r["projections"][0]
    assert proj["domain"] == "customer"
    assert proj["projection"] == "CustomerView"
    assert proj["version"] == 1

    field_names = {f["field_name"] for f in proj["fields"]}
    assert "customerId" in field_names
    assert "displayName" in field_names
    assert "isBillable" in field_names


def test_lineage_distinguishes_direct_and_computed():
    open_workspace()
    result = dispatch("workspace.lineage", {"workspaceRevision": 100})

    fields = {f["field_name"]: f for f in result["result"]["projections"][0]["fields"]}
    assert fields["customerId"]["kind"] == "direct"
    assert fields["customerId"]["expression"] is None
    assert len(fields["customerId"]["lineage"]) == 1

    assert fields["isBillable"]["kind"] == "computed"
    assert fields["isBillable"]["expression"] is not None


def test_lineage_empty_workspace():
    open_workspace(sources=[{"uri": URI, "text": EMPTY_SOURCE, "version": 1}])
    result = dispatch("workspace.lineage", {"workspaceRevision": 100})

    assert result["ok"]
    assert result["result"]["projections"] == []


def test_lineage_rejects_stale_workspace():
    open_workspace(50)
    result = dispatch("workspace.lineage", {"workspaceRevision": 49})

    assert not result["ok"]
    assert result["error"]["code"] == "STALE_WORKSPACE"


def test_lineage_rejects_extra_fields():
    open_workspace()
    result = dispatch("workspace.lineage", {"workspaceRevision": 100, "extra": True})

    assert not result["ok"]
    assert result["error"]["code"] == "INVALID_REQUEST"
