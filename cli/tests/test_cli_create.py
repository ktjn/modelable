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
