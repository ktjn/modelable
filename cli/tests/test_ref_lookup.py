from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.language.ref_lookup import REF_TYPE_PATTERN, resolve_ref_match_version


def _workspace(text: str):
    source = WorkspaceDocumentSource(path=Path("test.mdl"), uri="file:///test.mdl", text=text)
    return load_workspace_from_sources([source])


DOMAIN = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) { @key customerId: uuid }
  entity Customer @ 2 (additive) { @key customerId: uuid name: string }
}
"""


def test_pattern_matches_unversioned_ref():
    match = REF_TYPE_PATTERN.search("customerRef: ref<customer.Customer>")
    assert match is not None
    assert match.group("domain") == "customer"
    assert match.group("name") == "Customer"
    assert match.group("version") is None


def test_pattern_matches_exact_version():
    match = REF_TYPE_PATTERN.search("customerRef: ref<customer.Customer @ 2>")
    assert match is not None
    assert match.group("version") == "2"


def test_pattern_matches_range_version():
    match = REF_TYPE_PATTERN.search("customerRef: ref<customer.Customer @ >=1 <3>")
    assert match is not None
    assert match.group("version").replace(" ", "") == ">=1<3"


def test_pattern_matches_pinned_version():
    match = REF_TYPE_PATTERN.search("customerRef: ref<customer.Customer @ 2#deadbeef>")
    assert match is not None
    assert match.group("version") == "2#deadbeef"


def test_resolve_unversioned_returns_latest():
    workspace = _workspace(DOMAIN)
    version = resolve_ref_match_version(workspace, "customer", "Customer", None)
    assert version == 2


def test_resolve_exact_version_text():
    workspace = _workspace(DOMAIN)
    version = resolve_ref_match_version(workspace, "customer", "Customer", "1")
    assert version == 1


def test_resolve_unresolvable_returns_none():
    workspace = _workspace(DOMAIN)
    version = resolve_ref_match_version(workspace, "customer", "Customer", "99")
    assert version is None
