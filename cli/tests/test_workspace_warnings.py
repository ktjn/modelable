from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources


def test_deferred_syntax_produces_workspace_warning_not_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            materialisation {
              strategy: incremental
            }
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert workspace.errors == []
    assert len(workspace.warnings) == 1
    assert workspace.warnings[0].code == "DEFERRED"
    assert workspace.warnings[0].severity == "warning"
    assert workspace.sources[0].warnings == workspace.warnings


def test_no_deferred_syntax_produces_no_workspace_warnings():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert workspace.warnings == []
    assert workspace.sources[0].warnings == []
