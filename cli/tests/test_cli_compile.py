from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.extensions import PROTOCOL, ExtensionDescriptor, pin_extension_descriptor
from modelable.operations import compilation as compilation_module
from modelable.registry.snapshot import resolve_workspace_snapshot

_TWO_DOMAIN_MDL = """
domain logs {
  owner: "test-team"
  entity LogEntry @ 1 (additive) {
    @key logId: uuid
    message: string
  }
}

domain nlq {
  owner: "test-team"
  entity Query @ 1 (additive) {
    @key queryId: uuid
    text: string
  }
}
"""


def test_compile_domain_flag_restricts_output(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--domain", "logs", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert not (out / "nlq").exists()


def test_compile_domain_flag_is_additive(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            [
                "compile",
                str(mdl),
                "--target",
                "rust",
                "--domain",
                "logs",
                "--domain",
                "nlq",
                "--out",
                str(out),
            ],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert (out / "nlq" / "nlq_query_v1.rs").exists()


def test_compile_unknown_domain_errors_clearly(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--domain", "bogus", "--out", str(out)],
        )

    assert result.exit_code != 0
    assert "bogus" in result.output
    assert "logs" in result.output
    assert "nlq" in result.output
    assert not out.exists()


def test_compile_uses_offline_snapshot_for_external_reference(tmp_path: Path) -> None:
    provider = tmp_path / "provider.mdl"
    provider.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""",
        encoding="utf-8",
    )
    consumer = tmp_path / "consumer.mdl"
    consumer.write_text(
        """
domain analytics {
  owner: "analytics-platform"
  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.displayName
  }
    }
""",
        encoding="utf-8",
    )
    snapshot = tmp_path / ".modelable"
    descriptor = ExtensionDescriptor(
        protocol=PROTOCOL,
        id="example.target",
        version="1.2.3",
        accepted_plan_versions=("modelable.plan/v0",),
        capabilities=("records",),
        configuration_schema=None,
        output_kinds=("artifact",),
        compatibility_support=False,
    )
    pin = pin_extension_descriptor(descriptor, "a" * 64, source="oci://example/target")
    resolve_workspace_snapshot(load_workspace(provider), snapshot, extension_pins=(pin,))
    out = tmp_path / "dist" / "json-schema"

    result = CliRunner().invoke(
        cli,
        [
            "compile",
            str(consumer),
            "--target",
            "json-schema",
            "--snapshot",
            str(snapshot),
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (out / "analytics.CustomerSummary.v1.json").exists()
    manifest = json.loads((out / "modelable-artifact-manifest.json").read_text(encoding="utf-8"))
    assert manifest["extension_pins"] == [pin.as_dict()]


def test_compile_without_domain_flag_compiles_whole_workspace(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_TWO_DOMAIN_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--out", str(out)],
        )

    assert result.exit_code == 0, result.output
    assert (out / "logs" / "logs_log_entry_v1.rs").exists()
    assert (out / "nlq" / "nlq_query_v1.rs").exists()


def test_compile_writes_usage_manifest_with_generated_artifact_evidence(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""".strip(),
        encoding="utf-8",
    )
    out = tmp_path / "dist" / "typescript"

    result = CliRunner().invoke(
        cli,
        ["compile", str(source), "--target", "typescript", "--out", str(out), "--usage-manifest"],
    )

    assert result.exit_code == 0, result.output
    usage_path = out / "modelable-usage-manifest.json"
    manifest = json.loads(usage_path.read_text(encoding="utf-8"))
    assert manifest["$schema"] == "modelable.usage/v0"
    assert manifest["kind"] == "usage_manifest"
    assert manifest["references"][0]["ref"] == "customer.Customer@1"
    assert manifest["artifacts"] == [
        {
            "path": "customer.Customer.v1.ts",
            "ref": "customer.Customer@1",
            "sha256": json.loads((out / "modelable-artifact-manifest.json").read_text(encoding="utf-8"))["artifacts"][
                0
            ]["sha256"],
            "target": "typescript",
        }
    ]


def test_compile_rejects_unsupported_plan_protocol_before_writing_state(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )
    descriptor = ExtensionDescriptor(
        protocol=PROTOCOL,
        id="example.target",
        version="1.2.3",
        accepted_plan_versions=("modelable.plan/v1",),
        capabilities=("records",),
        configuration_schema=None,
        output_kinds=("language",),
        compatibility_support=False,
    )
    monkeypatch.setattr(
        compilation_module,
        "get_codegen_target",
        lambda _name: SimpleNamespace(extension_descriptor=lambda: descriptor),
    )
    out = tmp_path / "dist"

    result = CliRunner().invoke(cli, ["compile", str(source), "--target", "typescript", "--out", str(out)])

    assert result.exit_code == 1
    assert "does not accept plan protocol" in result.output
    assert not out.exists()
    assert not (tmp_path / ".modelable" / "registry.db").exists()
    assert not (tmp_path / ".modelable" / "plans").exists()
    assert not (tmp_path / "registry-ids.lock").exists()
    assert not (tmp_path / "enum-numbers.lock").exists()


def test_compile_rejects_invalid_snapshot_pins_before_writing_outputs(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )
    snapshot = tmp_path / ".modelable"
    snapshot.mkdir()
    (snapshot / "registry.lock").write_text(
        json.dumps(
            {
                "format": "modelable.registry.lock.v1",
                "extensions": [
                    {
                        "id": "example.target",
                        "version": "1.2.3",
                        "implementation_hash": "not-a-hash",
                        "source": None,
                        "accepted_protocol_versions": ["modelable.extension/v1"],
                    }
                ],
                "objects": [],
                "requirements": [],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "dist"

    result = CliRunner().invoke(cli, ["compile", str(source), "--target", "typescript", "--out", str(out)])

    assert result.exit_code == 1
    assert not out.exists()
    assert not (tmp_path / "registry-ids.lock").exists()
    assert not (tmp_path / "enum-numbers.lock").exists()


_CROSS_DOMAIN_PROJECTION_MDL = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}

domain billing {
  owner: "test-team"

  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    displayName <- c.displayName
  }
}
"""


def test_compile_domain_flag_errors_on_excluded_projection_source(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_CROSS_DOMAIN_PROJECTION_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "rust", "--domain", "billing", "--out", str(out)],
        )

    assert result.exit_code != 0
    assert "customer" in result.output
    assert "billing.BillingCustomer" in result.output
    assert not out.exists()


def test_compile_domain_flag_succeeds_when_projection_source_included(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(_CROSS_DOMAIN_PROJECTION_MDL, encoding="utf-8")
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            [
                "compile",
                str(mdl),
                "--target",
                "rust",
                "--domain",
                "billing",
                "--domain",
                "customer",
                "--out",
                str(out),
            ],
        )

    assert result.exit_code == 0, result.output
    text = (out / "billing" / "billing_billing_customer_v1.rs").read_text(encoding="utf-8")
    # The projection field must keep the source's real type (uuid), not degrade to a lossy String.
    assert "pub customer_id: uuid::Uuid," in text
    assert "pub customer_id: String," not in text


def test_compile_rust_domain_scope_allows_unrelated_duplicate_model_names(
    tmp_path,
):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain alpha {
  owner: "alpha-team"

  value Address @ 1 (additive) {
    line1: string
  }

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: Address
  }
}

domain beta {
  owner: "beta-team"

  value Address @ 1 (additive) {
    code: string
  }
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "dist" / "rust"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            [
                "compile",
                str(mdl),
                "--target",
                "rust",
                "--domain",
                "alpha",
                "--out",
                str(out),
            ],
        )

    assert result.exit_code == 0, result.output
    assert (out / "alpha").exists()
    assert not (out / "beta").exists()


def test_compile_custom_registry_ledger_keeps_plans_in_default_directory(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        cwd = Path(cwd)
        mdl = cwd / "workspace.mdl"
        mdl.write_text(
            """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
  }

  projection OrderView @ 1
    from platform.Order @ 1 as order
  {
    orderId <- order.orderId
  }
}
""",
            encoding="utf-8",
        )
        custom_ledger = cwd / "state" / "registry-ids.lock"

        result = runner.invoke(
            cli,
            [
                "compile",
                str(mdl),
                "--target",
                "rust",
                "--out",
                str(cwd / "dist"),
                "--registry-ids",
                str(custom_ledger),
            ],
        )

        assert result.exit_code == 0, result.output
        assert custom_ledger.exists()
        assert any((cwd / ".modelable" / "plans").glob("*.json"))
        assert not (custom_ledger.parent / ".modelable" / "plans").exists()


def test_compile_empty_domain_creates_requested_output_directory(tmp_path):
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "dist" / "rust"

    result = CliRunner().invoke(
        cli,
        ["compile", str(mdl), "--target", "rust", "--out", str(out)],
    )

    assert result.exit_code == 0, result.output
    assert "No artifacts generated." in result.output
    assert out.is_dir()
    assert (out / "modelable-artifact-manifest.json").exists()
