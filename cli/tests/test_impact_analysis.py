from click.testing import CliRunner

from modelable.cli import cli


def test_diff_reports_impacted_projections(tmp_path):
    (tmp_path / "customer.mdl").write_text("""
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
    email: string
  }
  entity Customer @ 2 (breaking) {
    @key customerId: uuid
    name: string
  }
}
    """.strip())
    
    (tmp_path / "billing.mdl").write_text("""
domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    id <- c.customerId
    emailAddress <- c.email
  }
}
    """.strip())

    (tmp_path / "shipping.mdl").write_text("""
domain shipping {
  owner: "test-team"
  projection ShippingLabel @ 1
    from customer.Customer @ 1 as c
  {
    labelId <- c.customerId
    recipientName <- c.name
  }
}
    """.strip())

    runner = CliRunner()
    result = runner.invoke(cli, ["diff", "customer.Customer@1", "customer.Customer@2", "--path", str(tmp_path)])
    
    assert result.exit_code == 1
    assert "status: breaking" in result.output
    assert "Impacted Projections:" in result.output
    assert "[BROKEN] billing.BillingCustomer@1" in result.output
    assert "uses field 'email' (removed_field)" in result.output
    assert "[AFFECTED] shipping.ShippingLabel@1" in result.output
    assert "source customer.Customer is marked" in result.output
    assert "breaking" in result.output

def test_diff_reports_no_impact_when_compatible(tmp_path):
    (tmp_path / "customer.mdl").write_text("""
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    name: string
    email?: string
  }
}
    """.strip())
    
    (tmp_path / "billing.mdl").write_text("""
domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    id <- c.customerId
    name <- c.name
  }
}
    """.strip())

    runner = CliRunner()
    result = runner.invoke(cli, ["diff", "customer.Customer@1", "customer.Customer@2", "--path", str(tmp_path)])
    
    assert result.exit_code == 0
    assert "status: compatible" in result.output
    # Compatible impacts are not shown by default in the current implementation
    assert "Impacted Projections:" not in result.output
