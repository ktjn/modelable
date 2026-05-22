from pathlib import Path

import pytest
from click.testing import CliRunner

from modelable.cli import cli


def test_create_domain_writes_mdl_file(tmp_path):
    result = CliRunner().invoke(
        cli, ["create", "domain", "--output-dir", str(tmp_path)], input="customer\n"
    )

    assert result.exit_code == 0
    out_file = tmp_path / "customer.mdl"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "domain customer {" in content


def test_create_domain_errors_if_file_exists(tmp_path):
    existing = tmp_path / "customer.mdl"
    existing.write_text("domain customer {}\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["create", "domain", "--output-dir", str(tmp_path)], input="customer\n"
    )

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_create_model_writes_entity_with_fields(tmp_path):
    # domain, kind, name, version (default=1), change_kind (default=additive),
    # field 1: name, type, optional?, @key?, @pii?,
    # field 2: name, type, optional?, @key?, @pii?,
    # blank name to finish
    user_input = "customer\nentity\nCustomer\n1\nadditive\ncustomerId\nuuid\nN\nY\nN\nemail\nstring\nY\nN\nN\n\n"

    result = CliRunner().invoke(
        cli, ["create", "model", "--output-dir", str(tmp_path)], input=user_input
    )

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
    result = CliRunner().invoke(
        cli, ["create", "model", "--output-dir", str(tmp_path)], input=user_input
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
