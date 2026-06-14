from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace


def test_create_domain_writes_mdl_file(tmp_path):
    result = CliRunner().invoke(cli, ["create", "domain", "--output-dir", str(tmp_path)], input="customer\n")

    assert result.exit_code == 0
    out_file = tmp_path / "customer.mdl"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "domain customer {" in content


def test_create_domain_errors_if_file_exists(tmp_path):
    existing = tmp_path / "customer.mdl"
    existing.write_text("domain customer {}\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["create", "domain", "--output-dir", str(tmp_path)], input="customer\n")

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_create_model_writes_entity_with_fields(tmp_path):
    # domain, kind, name, version (default=1), change_kind (default=additive),
    # field 1: name, type, optional?, @key?, @pii?,
    # field 2: name, type, optional?, @key?, @pii?,
    # blank name to finish
    user_input = "customer\nentity\nCustomer\n1\nadditive\ncustomerId\nuuid\nN\nY\nN\nemail\nstring\nY\nN\nN\n\n"

    result = CliRunner().invoke(cli, ["create", "model", "--output-dir", str(tmp_path)], input=user_input)

    assert result.exit_code == 0, result.output
    out_file = tmp_path / "customer.mdl"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "domain customer {" in content
    assert "entity Customer @ 1 (additive) {" in content
    assert "@key customerId: uuid" in content
    assert "email?: string" in content


def test_create_model_errors_if_file_exists(tmp_path):
    existing = tmp_path / "customer.mdl"
    existing.write_text("domain customer {}\n", encoding="utf-8")

    user_input = "customer\nentity\nCustomer\n1\nadditive\n\n"
    result = CliRunner().invoke(cli, ["create", "model", "--output-dir", str(tmp_path)], input=user_input)

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_create_projection_writes_projection_with_direct_and_computed_fields(tmp_path):
    user_input = (
        "billing\n"  # domain
        "BillingCustomer\n"  # projection name
        "1\n"  # version
        "customer.Customer\n"  # source model ref
        "1\n"  # source version
        "c\n"  # alias
        "billingId\n"  # field 1 name
        "c.customerId\n"  # field 1 mapping (direct)
        "displayEmail\n"  # field 2 name
        "c.email + ''\n"  # field 2 mapping (computed)
        "\n"  # blank = done
    )

    result = CliRunner().invoke(cli, ["create", "projection", "--output-dir", str(tmp_path)], input=user_input)

    assert result.exit_code == 0, result.output
    out_file = tmp_path / "billing.mdl"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "projection BillingCustomer @ 1" in content
    assert "from customer.Customer @ 1 as c" in content
    assert "billingId <- c.customerId" in content
    assert "displayEmail = c.email + ''" in content


def test_create_model_decimal_field_produces_valid_mdl(tmp_path):
    # decimal requires precision and scale: decimal(18, 2) — bare "decimal" is invalid syntax
    # use value kind (no @key required) to keep the test focused on decimal formatting
    user_input = "orders\nvalue\nMoney\n1\nadditive\ntotal\ndecimal\n18\n2\nN\nN\nN\n\n"

    result = CliRunner().invoke(cli, ["create", "model", "--output-dir", str(tmp_path)], input=user_input)

    assert result.exit_code == 0, result.output
    content = (tmp_path / "orders.mdl").read_text(encoding="utf-8")
    assert "total: decimal(18, 2)" in content
    workspace = load_workspace(tmp_path)
    assert workspace.errors == []


def test_create_projection_errors_if_file_exists(tmp_path):
    existing = tmp_path / "billing.mdl"
    existing.write_text("domain billing {}\n", encoding="utf-8")

    user_input = "billing\nBillingCustomer\n1\ncustomer.Customer\n1\nc\n\n"
    result = CliRunner().invoke(cli, ["create", "projection", "--output-dir", str(tmp_path)], input=user_input)

    assert result.exit_code != 0
    assert "already exists" in result.output
