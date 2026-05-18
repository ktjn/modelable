from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource
from modelable.lsp.federation import build_import_diagnostics
from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.compiler.workspace import WorkspaceDocumentSource


IMPORT_TEXT = """
import domain customer from registry "customer-platform-registry"
""".strip(
    "\n"
)

WORKSPACE_WITH_MISSING_PEER = """
workspace "analytics-platform" {
  registry {
    id: "analytics-registry"
    owns: ["analytics"]
  }

  peers: [
    {
      id: "orders-registry"
      git: "git@github.com:acme/orders-models.git"
    }
  ]
}
""".strip(
    "\n"
)

WORKSPACE_WITH_KNOWN_PEER = """
workspace "analytics-platform" {
  registry {
    id: "analytics-registry"
    owns: ["analytics"]
  }

  peers: [
    {
      id: "customer-platform-registry"
      git: "git@github.com:acme/customer-models.git"
    }
  ]
}
""".strip(
    "\n"
)

MIRROR_CUSTOMER_TEXT = """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(
    "\n"
)


def _index(tmp_path: Path, workspace_text: str, *, mirror: bool) -> LspWorkspaceIndex:
    workspace_path = tmp_path / "workspace.mdl"
    workspace_path.write_text(workspace_text, encoding="utf-8")
    import_path = tmp_path / "billing.mdl"
    import_path.write_text(IMPORT_TEXT, encoding="utf-8")

    if mirror:
        mirror_path = tmp_path / ".modelable" / "mirror" / "peer" / "customer.mdl"
        mirror_path.parent.mkdir(parents=True, exist_ok=True)
        mirror_path.write_text(MIRROR_CUSTOMER_TEXT, encoding="utf-8")

    index = LspWorkspaceIndex()
    index.documents[workspace_path.as_uri()] = WorkspaceDocumentSource(
        path=workspace_path,
        uri=workspace_path.as_uri(),
        text=workspace_text,
    )
    index.documents[import_path.as_uri()] = WorkspaceDocumentSource(
        path=import_path,
        uri=import_path.as_uri(),
        text=IMPORT_TEXT,
    )
    return index


def test_import_diagnostics_warn_when_peer_is_not_declared(tmp_path):
    index = _index(tmp_path, WORKSPACE_WITH_MISSING_PEER, mirror=True)

    diagnostics = build_import_diagnostics(index, (tmp_path / "billing.mdl").as_uri())

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "FED"
    assert diagnostics[0].severity == "warning"
    assert "peer 'customer-platform-registry' is not declared" in diagnostics[0].message


def test_import_diagnostics_error_when_mirror_domain_is_missing(tmp_path):
    index = _index(tmp_path, WORKSPACE_WITH_KNOWN_PEER, mirror=False)

    diagnostics = build_import_diagnostics(index, (tmp_path / "billing.mdl").as_uri())

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "FED"
    assert diagnostics[0].severity == "error"
    assert "domain 'customer' is not available" in diagnostics[0].message
