import hashlib

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.python import emit_python


def test_emit_python_model_and_projection(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
    tags: array<string>
    nickname?: string
    attributes?: map<string, int>
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
    tags <- c.tags
    nickname <- c.nickname
    attributes <- c.attributes
    address <- c.address
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_python(workspace, tmp_path / "out")
    refs = {artifact.ref for artifact in artifacts}
    assert "customer.Customer@1" in refs
    assert "customer.CustomerView@1" in refs

    model_art = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    assert model_art.content_hash == hashlib.sha256(model_art.content.encode("utf-8")).hexdigest()
    assert model_art.path.as_posix().endswith("customer/customer_customer_v1.py")
    assert "from __future__ import annotations" in model_art.content
    assert "from dataclasses import dataclass" in model_art.content
    assert "class CustomerCustomerV1:" in model_art.content
    assert "customerId: UUID" in model_art.content
    assert "displayName: str" in model_art.content
    assert "tags: list[str]" in model_art.content
    assert "nickname: Optional[str] = None" in model_art.content
    assert "attributes: Optional[dict[str, int]] = None" in model_art.content
    assert "address: Optional[CustomerCustomerV1Address] = None" in model_art.content
    assert "class CustomerCustomerV1Address:" in model_art.content
    assert "line1: str" in model_art.content
    assert "line2: Optional[str] = None" in model_art.content

    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")
    assert proj_art.content_hash == hashlib.sha256(proj_art.content.encode("utf-8")).hexdigest()
    assert proj_art.path.as_posix().endswith("customer/customer_customer_view_v1.py")
    assert "class CustomerCustomerViewV1:" in proj_art.content
    assert "customerId: UUID" in proj_art.content
    assert "displayName: str" in proj_art.content
    assert "tags: list[str]" in proj_art.content
    assert "nickname: Optional[str] = None" in proj_art.content
    assert "attributes: Optional[dict[str, int]] = None" in proj_art.content
    assert "address: Optional[CustomerCustomerViewV1Address] = None" in proj_art.content
    assert "class CustomerCustomerViewV1Address:" in proj_art.content


def test_cli_compile_python_writes_files(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
    nickname?: string
  }
}
""",
        encoding="utf-8",
    )

    out = tmp_path / "dist" / "python"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "python", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "customer" / "customer_customer_v1.py").exists()
    assert any(len(part) == 64 and all(ch in "0123456789abcdef" for ch in part.lower()) for part in result.output.split())
    text = (out / "customer" / "customer_customer_v1.py").read_text(encoding="utf-8")
    assert "class CustomerCustomerV1:" in text
    assert "customerId: UUID" in text
    assert "nickname: Optional[str] = None" in text


def test_emit_python_decimal_maps_to_decimal(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain finance {
  owner: "test-team"
  entity Invoice @ 1 (additive) {
    @key invoiceId: uuid
    amount: decimal(12, 2)
    taxRate?: decimal(5, 4)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_python(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "finance.Invoice@1")
    assert "from decimal import Decimal" in art.content
    assert "amount: Decimal" in art.content
    assert "taxRate: Optional[Decimal] = None" in art.content


def test_emit_python_temporal_types_map_to_datetime(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain events {
  owner: "test-team"
  entity Event @ 1 (additive) {
    @key eventId: uuid
    occurredAt: timestamp
    scheduledDate: date
    windowStart: time
    ttl: duration
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_python(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "events.Event@1")
    assert "from datetime import date, datetime, time, timedelta" in art.content
    assert "occurredAt: datetime" in art.content
    assert "scheduledDate: date" in art.content
    assert "windowStart: time" in art.content
    assert "ttl: timedelta" in art.content


def test_emit_python_warns_on_computed_projection_field(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
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
    from modelable.emitters.python import emit_python
    workspace = load_workspace(tmp_path)
    artifacts = emit_python(workspace, tmp_path / "out")
    proj_art = next(a for a in artifacts if a.ref == "customer.CustomerView@1")
    assert proj_art.warnings
    assert any("EMIT002" in w for w in proj_art.warnings)


def test_emit_python_projection_uses_source_field_types(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
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
    from modelable.emitters.python import emit_python
    workspace = load_workspace(tmp_path)
    artifacts = emit_python(workspace, tmp_path / "out")
    proj_art = next(a for a in artifacts if a.ref == "customer.CustomerView@2")
    # name comes from Customer@1 (str), not Customer@2 (int)
    assert "name: str" in proj_art.content
