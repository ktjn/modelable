import hashlib

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.csharp import emit_csharp


def test_emit_csharp_model_and_projection(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
    nickname?: string
    age?: int
    address?: object {
      line1: string
      line2?: string
    }
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    displayName <- c.displayName
    nickname <- c.nickname
    address <- c.address
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_csharp(workspace, tmp_path / "out")
    refs = {artifact.ref for artifact in artifacts}
    assert "customer.Customer@1" in refs
    assert "customer.CustomerView@1" in refs

    model_art = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    assert model_art.content_hash == hashlib.sha256(model_art.content.encode("utf-8")).hexdigest()
    assert model_art.path.name == "customer.Customer.v1.cs"
    assert "namespace Modelable.Customer;" in model_art.content
    assert "public sealed record CustomerCustomerV1" in model_art.content
    assert "public required Guid CustomerId { get; init; }" in model_art.content
    assert "public string? Nickname { get; init; }" in model_art.content
    assert "public int? Age { get; init; }" in model_art.content
    assert "public CustomerCustomerV1Address? Address { get; init; }" in model_art.content
    assert "public sealed record CustomerCustomerV1Address" in model_art.content
    assert "public required string Line1 { get; init; }" in model_art.content
    assert "public string? Line2 { get; init; }" in model_art.content

    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")
    assert proj_art.content_hash == hashlib.sha256(proj_art.content.encode("utf-8")).hexdigest()
    assert proj_art.path.name == "customer.CustomerView.v1.cs"
    assert "namespace Modelable.Customer;" in proj_art.content
    assert "public sealed record CustomerCustomerViewV1" in proj_art.content
    assert "public required Guid CustomerId { get; init; }" in proj_art.content
    assert "public required string DisplayName { get; init; }" in proj_art.content
    assert "public string? Nickname { get; init; }" in proj_art.content
    assert "public CustomerCustomerViewV1Address? Address { get; init; }" in proj_art.content
    assert "public sealed record CustomerCustomerViewV1Address" in proj_art.content


def test_cli_compile_csharp_writes_files(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
    nickname?: string
  }
}
""",
        encoding="utf-8",
    )

    out = tmp_path / "dist" / "csharp"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "csharp", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "customer.Customer.v1.cs").exists()
    assert any(len(part) == 64 and all(ch in "0123456789abcdef" for ch in part.lower()) for part in result.output.split())
    text = (out / "customer.Customer.v1.cs").read_text(encoding="utf-8")
    assert "namespace Modelable.Customer;" in text
    assert "public sealed record CustomerCustomerV1" in text
    assert "public required Guid CustomerId { get; init; }" in text
    assert "public string? Nickname { get; init; }" in text


def test_emit_csharp_warns_on_computed_projection_field(tmp_path):
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
    displayName = c.name + "!"
  }
}
""",
        encoding="utf-8",
    )
    from modelable.compiler.workspace import load_workspace
    workspace = load_workspace(tmp_path)
    artifacts = emit_csharp(workspace, tmp_path / "out")
    proj_art = next(a for a in artifacts if a.ref == "customer.CustomerView@1")
    assert proj_art.warnings
    assert any("EMIT002" in w for w in proj_art.warnings)


def test_emit_csharp_projection_uses_source_field_types(tmp_path):
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
    from modelable.compiler.workspace import load_workspace
    workspace = load_workspace(tmp_path)
    artifacts = emit_csharp(workspace, tmp_path / "out")
    proj_art = next(a for a in artifacts if a.ref == "customer.CustomerView@2")
    # name comes from Customer@1 (string), not Customer@2 (int)
    assert "string Name" in proj_art.content or "string name" in proj_art.content.lower()
