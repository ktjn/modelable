from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.parser.parse import parse_text_to_ir

SINGLE_PACKAGE = """
workspace "test-workspace" {
  package "my-package" {
    include: ["dom1", "dom2"]
  }
}
"""


def test_parses_single_package_block():
    mdl = parse_text_to_ir(SINGLE_PACKAGE)
    assert mdl.workspace is not None
    assert len(mdl.workspace.packages) == 1
    pkg = mdl.workspace.packages[0]
    assert pkg.name == "my-package"
    assert pkg.include == ["dom1", "dom2"]


MULTI_PACKAGE = """
workspace "test-workspace" {
  package "pkg-a" {
    include: ["dom1"]
  }
  package "pkg-b" {
    include: ["dom2"]
    description: "Package B"
  }
}
"""


def test_parses_multiple_package_blocks():
    mdl = parse_text_to_ir(MULTI_PACKAGE)
    assert mdl.workspace is not None
    assert len(mdl.workspace.packages) == 2
    assert mdl.workspace.packages[0].name == "pkg-a"
    assert mdl.workspace.packages[1].name == "pkg-b"
    assert mdl.workspace.packages[1].description == "Package B"


EMPTY_INCLUDE = """
workspace "test-workspace" {
  package "empty-pkg" {
    include: []
  }
}
"""


def test_empty_include_list():
    mdl = parse_text_to_ir(EMPTY_INCLUDE)
    assert mdl.workspace is not None
    assert mdl.workspace.packages[0].include == []


NO_PACKAGES = """
workspace "test-workspace" {
  name: "test"
}
"""


def test_no_packages_is_valid():
    mdl = parse_text_to_ir(NO_PACKAGES)
    assert mdl.workspace is not None
    assert mdl.workspace.packages == []


def _mdl_text(domain1_body: str, domain2_body: str, package_block: str) -> str:
    return f"""
domain dom1 {{
  owner: "team-a"
  entity Thing1 @ 1 (additive) {{
    {domain1_body}
  }}
}}

domain dom2 {{
  owner: "team-b"
  entity Thing2 @ 1 (additive) {{
    {domain2_body}
  }}
}}

workspace "test-workspace" {{
  {package_block}
}}
"""


def test_package_config_rejects_domain_assigned_to_multiple_packages(tmp_path):
    text = _mdl_text(
        "@key id: uuid",
        "@key id: uuid",
        """
  package "pkg-a" {
    include: ["dom1"]
  }
  package "pkg-b" {
    include: ["dom1"]
  }
""",
    )
    source = WorkspaceDocumentSource(path=None, uri="mem://test.mdl", text=text)
    workspace = load_workspace_from_sources([source])
    assert any("dom1" in error.message and "multiple packages" in error.message for error in workspace.errors)


def test_package_config_allows_domains_in_distinct_packages(tmp_path):
    text = _mdl_text(
        "@key id: uuid",
        "@key id: uuid",
        """
  package "pkg-a" {
    include: ["dom1"]
  }
  package "pkg-b" {
    include: ["dom2"]
  }
""",
    )
    source = WorkspaceDocumentSource(path=None, uri="mem://test.mdl", text=text)
    workspace = load_workspace_from_sources([source])
    assert workspace.errors == []
