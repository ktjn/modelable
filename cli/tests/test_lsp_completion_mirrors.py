from pathlib import Path

from modelable.lsp.completion import build_completion
from modelable.lsp.federation import mirror_reference_names
from modelable.lsp.workspace import LspWorkspaceIndex


WORKSPACE_TEXT = """

domain local {
  entity Local @ 1 (additive) {
    @key localId: uuid
  }
}
""".strip(
    "\n"
)

MIRROR_TEXT = """
domain supplier {
  entity Supplier @ 1 (additive) {
    @key supplierId: uuid
  }

  projection SupplierView @ 1
    from supplier.Supplier @ 1 as s
  {
    supplierId <- s.supplierId
  }
}
""".strip(
    "\n"
)


def _index(tmp_path: Path) -> LspWorkspaceIndex:
    workspace_path = tmp_path / "workspace.mdl"
    workspace_path.write_text(WORKSPACE_TEXT, encoding="utf-8")
    mirror_path = tmp_path / ".modelable" / "mirror" / "peer" / "supplier.mdl"
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    mirror_path.write_text(MIRROR_TEXT, encoding="utf-8")

    index = LspWorkspaceIndex()
    index.upsert_document(workspace_path.as_uri(), WORKSPACE_TEXT)
    return index


def test_completion_includes_mirror_domain_names(tmp_path):
    index = _index(tmp_path)
    completion = build_completion(index, (tmp_path / "workspace.mdl").as_uri(), line=0, character=0)

    labels = [item.label for item in completion.items]
    assert "supplier" in labels


def test_mirror_completion_indexes_model_and_projection_names(tmp_path):
    index = _index(tmp_path)

    assert ("supplier", "Supplier") in mirror_reference_names(index)
    assert ("supplier", "SupplierView") in mirror_reference_names(index)
