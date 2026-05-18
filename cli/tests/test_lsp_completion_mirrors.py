from pathlib import Path

from modelable.lsp.completion import build_completion
from modelable.lsp.federation import mirror_reference_names
from modelable.compiler.workspace import WorkspaceDocumentSource
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


def test_mirror_completion_suggests_pinned_reference_versions(tmp_path):
    index = _index(tmp_path)
    billing_path = tmp_path / "billing.mdl"
    billing_text = """
projection BillingCustomer @ 1
  from supplier.Supplier @1
{
  supplierId <- s.supplierId
}
""".strip(
        "\n"
    )
    index.documents[billing_path.as_uri()] = WorkspaceDocumentSource(
        path=billing_path,
        uri=billing_path.as_uri(),
        text=billing_text,
    )

    completion = build_completion(
        index,
        billing_path.as_uri(),
        line=1,
        character=len("  from supplier.Supplier @1"),
    )

    labels = [item.label for item in completion.items]
    assert "1" in labels


def test_mirror_completion_suggests_source_alias_fields(tmp_path):
    index = _index(tmp_path)
    billing_path = tmp_path / "billing.mdl"
    billing_text = """
domain billing {
  projection BillingCustomer @ 1
    from supplier.Supplier @ 1 as s
  {
    s.
  }
}
""".strip(
        "\n"
    )
    index.documents[billing_path.as_uri()] = WorkspaceDocumentSource(
        path=billing_path,
        uri=billing_path.as_uri(),
        text=billing_text,
    )

    completion = build_completion(
        index,
        billing_path.as_uri(),
        line=4,
        character=len("    s."),
    )

    labels = [item.label for item in completion.items]
    assert "supplierId" in labels


def test_mirror_completion_suggests_join_alias_fields(tmp_path):
    index = _index(tmp_path)
    billing_path = tmp_path / "billing.mdl"
    billing_text = """
domain billing {
  projection BillingCustomer @ 1
    from local.Local @ 1 as l
    join supplier.Supplier @ 1 as s on l.localId = s.supplierId
  {
    s.
  }
}
""".strip(
        "\n"
    )
    index.documents[billing_path.as_uri()] = WorkspaceDocumentSource(
        path=billing_path,
        uri=billing_path.as_uri(),
        text=billing_text,
    )

    completion = build_completion(
        index,
        billing_path.as_uri(),
        line=5,
        character=len("    s."),
    )

    labels = [item.label for item in completion.items]
    assert "supplierId" in labels


def test_mirror_completion_suggests_prefixed_join_alias_fields(tmp_path):
    index = _index(tmp_path)
    billing_path = tmp_path / "billing.mdl"
    billing_text = """
domain billing {
  projection BillingCustomer @ 1
    from local.Local @ 1 as l
    join supplier.Supplier @ 1 as s on l.localId = s.su
  {
    s.su
  }
}
""".strip(
        "\n"
    )
    index.documents[billing_path.as_uri()] = WorkspaceDocumentSource(
        path=billing_path,
        uri=billing_path.as_uri(),
        text=billing_text,
    )

    completion = build_completion(
        index,
        billing_path.as_uri(),
        line=5,
        character=len("    s.su"),
    )

    labels = [item.label for item in completion.items]
    assert labels == ["supplierId"]


def test_completion_suggests_prefixed_local_alias_fields(tmp_path):
    index = _index(tmp_path)
    billing_path = tmp_path / "billing.mdl"
    billing_text = """
domain billing {
  projection BillingLocal @ 1
    from local.Local @ 1 as l
  {
    l.lo
  }
}
""".strip(
        "\n"
    )
    index.documents[billing_path.as_uri()] = WorkspaceDocumentSource(
        path=billing_path,
        uri=billing_path.as_uri(),
        text=billing_text,
    )

    completion = build_completion(
        index,
        billing_path.as_uri(),
        line=4,
        character=len("    l.lo"),
    )

    labels = [item.label for item in completion.items]
    assert labels == ["localId"]


def test_mirror_completion_suggests_pinned_import_model_names(tmp_path):
    index = _index(tmp_path)
    billing_path = tmp_path / "billing.mdl"
    billing_text = """
import domain supplier from registry "supplier-platform-registry" at supplier.S
""".strip(
        "\n"
    )
    index.documents[billing_path.as_uri()] = WorkspaceDocumentSource(
        path=billing_path,
        uri=billing_path.as_uri(),
        text=billing_text,
    )

    completion = build_completion(
        index,
        billing_path.as_uri(),
        line=0,
        character=len('import domain supplier from registry "supplier-platform-registry" at supplier.S'),
    )

    labels = [item.label for item in completion.items]
    assert "Supplier" in labels
    assert "SupplierView" in labels


def test_mirror_completion_suggests_pinned_import_versions(tmp_path):
    index = _index(tmp_path)
    billing_path = tmp_path / "billing.mdl"
    billing_text = """
import domain supplier from registry "supplier-platform-registry" at supplier.Supplier @
""".strip(
        "\n"
    )
    index.documents[billing_path.as_uri()] = WorkspaceDocumentSource(
        path=billing_path,
        uri=billing_path.as_uri(),
        text=billing_text,
    )

    completion = build_completion(
        index,
        billing_path.as_uri(),
        line=0,
        character=len('import domain supplier from registry "supplier-platform-registry" at supplier.Supplier @'),
    )

    labels = [item.label for item in completion.items]
    assert labels == ["1"]


def test_mirror_completion_suggests_prefixed_pinned_import_versions(tmp_path):
    index = _index(tmp_path)
    billing_path = tmp_path / "billing.mdl"
    billing_text = """
import domain supplier from registry "supplier-platform-registry" at supplier.Supplier @1
""".strip(
        "\n"
    )
    index.documents[billing_path.as_uri()] = WorkspaceDocumentSource(
        path=billing_path,
        uri=billing_path.as_uri(),
        text=billing_text,
    )

    completion = build_completion(
        index,
        billing_path.as_uri(),
        line=0,
        character=len('import domain supplier from registry "supplier-platform-registry" at supplier.Supplier @1'),
    )

    labels = [item.label for item in completion.items]
    assert labels == ["1"]
