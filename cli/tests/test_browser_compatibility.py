import json

import pytest

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import dispatch_browser_request

COMPAT_SOURCE = (
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
    "    email?: string\n"
    "  }\n"
    "}\n"
)
URI = "file:///customer.mdl"
SOURCES = [{"uri": URI, "text": COMPAT_SOURCE, "version": 1}]

SINGLE_VERSION_SOURCE = (
    'domain customer {\n  owner: "team"\n  entity Customer @ 1 (additive) {\n    @key customerId: uuid\n  }\n}\n'
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


def test_compatibility_returns_report_for_consecutive_versions():
    open_workspace()
    result = dispatch("workspace.compatibility", {"workspaceRevision": 100})

    assert result["ok"]
    r = result["result"]
    assert r["workspace_revision"] == 100
    assert len(r["reports"]) == 1

    report = r["reports"][0]
    assert report["domain_name"] == "customer"
    assert report["model_name"] == "Customer"
    assert report["from_version"] == 1
    assert report["to_version"] == 2
    assert report["status"] == "compatible"
    assert len(report["changes"]) > 0


def test_compatibility_detects_added_fields():
    open_workspace()
    result = dispatch("workspace.compatibility", {"workspaceRevision": 100})

    changes = result["result"]["reports"][0]["changes"]
    added = [c for c in changes if c["kind"] == "added_field"]
    assert len(added) == 1
    assert added[0]["field_name"] == "email"
    assert added[0]["to_optional"] is True


def test_compatibility_single_version_returns_empty():
    open_workspace(sources=[{"uri": URI, "text": SINGLE_VERSION_SOURCE, "version": 1}])
    result = dispatch("workspace.compatibility", {"workspaceRevision": 100})

    assert result["ok"]
    assert result["result"]["reports"] == []
    assert result["result"]["impacts"] == []


def test_compatibility_rejects_stale_workspace():
    open_workspace(50)
    result = dispatch("workspace.compatibility", {"workspaceRevision": 49})

    assert not result["ok"]
    assert result["error"]["code"] == "STALE_WORKSPACE"


def test_compatibility_rejects_extra_fields():
    open_workspace()
    result = dispatch("workspace.compatibility", {"workspaceRevision": 100, "extra": True})

    assert not result["ok"]
    assert result["error"]["code"] == "INVALID_REQUEST"
