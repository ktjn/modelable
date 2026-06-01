from click.testing import CliRunner
from modelable.cli import cli


def test_inspect_auto_projections(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        name: string
      }

      auto projections Product @ 1 {
        db
        reply
      }
    }
    """)
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", "catalog.Product@1", "--auto", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "catalog.ProductDb@1" in result.output
    assert "catalog.ProductReply@1" in result.output
    assert "productId" in result.output
    assert "name" in result.output


def test_inspect_auto_request_excludes_server(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        name: string
        @server createdAt: timestamp
      }

      auto projections Product @ 1 {
        request
      }
    }
    """)
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", "catalog.Product@1", "--auto", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "productId" in result.output
    assert "name" in result.output
    assert "createdAt" not in result.output


def test_inspect_missing_domain(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
      }
    }
    """)
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", "missing.Product@1", "--auto", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "domain 'missing' not found" in result.output


def test_inspect_auto_supports_version_ranges(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        name: string
      }

      entity Product @ 2 (additive) {
        @key productId: uuid
        name: string
        email?: string
      }

      auto projections Product @ 1 {
        db
      }

      auto projections Product @ 2 {
        db
      }
    }
    """,
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", "catalog.Product@>=1<2", "--auto", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "catalog.ProductDb@1" in result.output
    assert "name" in result.output


def test_inspect_model_without_auto(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text("""
    domain catalog {
      owner: "test-team"
      entity Product @ 1 (additive) {
        @key productId: uuid
        name: string
      }
    }
    """)
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", "catalog.Product@1", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "Product" in result.output
    assert "productId" in result.output
    assert "name" in result.output


def test_inspect_projection_without_auto(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        email?: string
      }
    }

    domain billing {
      owner: "test-team"
      projection BillingCustomer @ 1
        from customer.Customer @ 1 as c
      {
        billingId <- c.customerId
      }
    }
    """)
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", "billing.BillingCustomer@1", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "BillingCustomer" in result.output
    assert "billingId" in result.output
