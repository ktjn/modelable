import hashlib

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.java import emit_java


def test_emit_java_model_and_projection(tmp_path):
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
    artifacts = emit_java(workspace, tmp_path / "out")
    refs = {artifact.ref for artifact in artifacts}
    assert "customer.Customer@1" in refs
    assert "customer.CustomerView@1" in refs

    model_art = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    assert model_art.content_hash == hashlib.sha256(model_art.content.encode("utf-8")).hexdigest()
    assert model_art.path.as_posix().endswith("customer/CustomerV1.java")
    assert "package customer;" in model_art.content
    assert "public record CustomerV1(" in model_art.content
    assert "UUID customerId" in model_art.content
    assert "Optional<String> nickname" in model_art.content
    assert "Optional<Long> age" in model_art.content
    assert "Optional<Address> address" in model_art.content
    assert "public record Address(" in model_art.content
    assert "String line1" in model_art.content
    assert "Optional<String> line2" in model_art.content

    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")
    assert proj_art.content_hash == hashlib.sha256(proj_art.content.encode("utf-8")).hexdigest()
    assert proj_art.path.as_posix().endswith("customer/CustomerViewV1.java")
    assert "package customer;" in proj_art.content
    assert "public record CustomerViewV1(" in proj_art.content
    assert "UUID customerId" in proj_art.content
    assert "String displayName" in proj_art.content
    assert "Optional<String> nickname" in proj_art.content
    assert "Optional<Address> address" in proj_art.content
    assert "public record Address(" in proj_art.content


def test_cli_compile_java_writes_files(tmp_path):
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

    out = tmp_path / "dist" / "java"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "java", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "customer" / "CustomerV1.java").exists()
    assert any(len(part) == 64 and all(ch in "0123456789abcdef" for ch in part.lower()) for part in result.output.split())
    text = (out / "customer" / "CustomerV1.java").read_text(encoding="utf-8")
    assert "package customer;" in text
    assert "public record CustomerV1(" in text
    assert "UUID customerId" in text
    assert "Optional<String> nickname" in text


def test_emit_java_warns_on_computed_projection_field(tmp_path):
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
    from modelable.emitters.java import emit_java
    workspace = load_workspace(tmp_path)
    artifacts = emit_java(workspace, tmp_path / "out")
    proj_art = next(a for a in artifacts if a.ref == "customer.CustomerView@1")
    assert proj_art.warnings
    assert any("EMIT002" in w for w in proj_art.warnings)


def test_emit_java_projection_uses_source_field_types(tmp_path):
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
    from modelable.emitters.java import emit_java
    workspace = load_workspace(tmp_path)
    artifacts = emit_java(workspace, tmp_path / "out")
    proj_art = next(a for a in artifacts if a.ref == "customer.CustomerView@2")
    # name comes from Customer@1 (String), not Customer@2 (Long)
    assert "String name" in proj_art.content
