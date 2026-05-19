from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.typescript import emit_typescript


def test_emit_typescript_model_and_projection(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
    age?: int
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    refs = {artifact.ref for artifact in artifacts}
    assert "customer.Customer@1" in refs
    assert "customer.CustomerView@1" in refs

    model_art = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    assert "export interface CustomerCustomerV1" in model_art.content
    assert "export type Customer = CustomerCustomerV1;" in model_art.content
    assert "/**" in model_art.content
    assert "@modelable domain: customer" in model_art.content
    assert "@modelable kind: entity" in model_art.content
    assert "age?: number" in model_art.content

    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")
    assert "export interface CustomerCustomerViewV1" in proj_art.content
    assert "export type CustomerView = CustomerCustomerViewV1;" in proj_art.content
    assert "@modelable source: customer.Customer@1" in proj_art.content


def test_emit_typescript_projection_uses_source_version_types(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  entity Customer @ 2 (additive) {
    @key customerId: uuid
    name: int
    email: string
  }

  projection CustomerView @ 2
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@2")
    assert "customerId: string" in proj_art.content
    assert "name: string" in proj_art.content


def test_emit_typescript_uses_stable_interface_names(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    model_art = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")

    assert "export interface CustomerCustomerV1" in model_art.content
    assert "export interface CustomerCustomerViewV1" in proj_art.content


def test_cli_compile_typescript_writes_files(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    out = tmp_path / "dist" / "types"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "typescript", "--out", str(out)],
        )

    assert result.exit_code == 0
    assert (out / "customer.Customer.v1.ts").exists()
    text = (out / "customer.Customer.v1.ts").read_text(encoding="utf-8")
    assert "export interface CustomerCustomerV1" in text
    assert "export type Customer = CustomerCustomerV1;" in text
