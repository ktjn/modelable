from __future__ import annotations

import hashlib
from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource
from modelable.llm.render import render_model_version
from modelable.lsp.federation import build_import_diagnostics
from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.parser.ir import AnnKey, FieldDef, ModelKind, ModelVersion, PrimitiveType


IMPORT_TEXT = """
import domain customer from registry "customer-platform-registry"
""".strip(
    "\n"
)

PINNED_IMPORT_TEXT = """
import domain customer from registry "customer-platform-registry" at customer.Customer@1#{signature}
""".strip(
    "\n"
)

PINNED_REFERENCE_TEXT = """
projection BillingCustomer @ 1
  from customer.Customer @ 1#{signature} as c
{
  customerId <- c.customerId
}
""".strip(
    "\n"
)

PINNED_MISSING_REFERENCE_TEXT = """
projection BillingCustomer @ 1
  from customer.Customer @ 1#{signature} as c
{
  customerId <- c.customerId
}
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


def _customer_signature() -> str:
    version = ModelVersion(
        model_kind=ModelKind.entity,
        version=1,
        change_kind="additive",
        fields=[
            FieldDef(
                name="customerId",
                type=PrimitiveType(kind="uuid"),
                annotations=[AnnKey()],
            )
        ],
    )
    text = render_model_version("customer", "Customer", version)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _index(
    tmp_path: Path,
    workspace_text: str,
    *,
    mirror: bool,
    import_text: str = IMPORT_TEXT,
) -> LspWorkspaceIndex:
    workspace_path = tmp_path / "workspace.mdl"
    workspace_path.write_text(workspace_text, encoding="utf-8")
    import_path = tmp_path / "billing.mdl"
    rendered_import_text = import_text.replace("{signature}", _customer_signature())
    import_path.write_text(rendered_import_text, encoding="utf-8")

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
        text=rendered_import_text,
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


def test_import_diagnostics_accepts_matching_pinned_import(tmp_path):
    index = _index(tmp_path, WORKSPACE_WITH_KNOWN_PEER, mirror=True, import_text=PINNED_IMPORT_TEXT)

    diagnostics = build_import_diagnostics(index, (tmp_path / "billing.mdl").as_uri())

    assert diagnostics == []


def test_import_diagnostics_errors_on_mismatched_pinned_reference(tmp_path):
    signature = _customer_signature()
    mismatched_signature = "0" * len(signature)
    index = _index(
        tmp_path,
        WORKSPACE_WITH_KNOWN_PEER,
        mirror=True,
        import_text=PINNED_REFERENCE_TEXT.replace("{signature}", mismatched_signature),
    )

    diagnostics = build_import_diagnostics(index, (tmp_path / "billing.mdl").as_uri())

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "FED"
    assert diagnostics[0].severity == "error"
    assert "does not match local mirror signature" in diagnostics[0].message


def test_import_diagnostics_errors_when_pinned_reference_missing_from_mirror(tmp_path):
    signature = _customer_signature()
    index = _index(
        tmp_path,
        WORKSPACE_WITH_KNOWN_PEER,
        mirror=False,
        import_text=PINNED_MISSING_REFERENCE_TEXT.replace("{signature}", signature),
    )

    diagnostics = build_import_diagnostics(index, (tmp_path / "billing.mdl").as_uri())

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "FED"
    assert diagnostics[0].severity == "error"
    assert "is not available in the local mirror cache" in diagnostics[0].message
