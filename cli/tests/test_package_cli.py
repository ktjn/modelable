import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.registry.snapshot import resolve_workspace_snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def _write_manifest(path: Path) -> None:
    path.write_text(
        """
[package]
name = "customer.contracts"
version = "1.2.3"

[exports]
declarations = ["customer.Customer@1"]
""",
        encoding="utf-8",
    )


def test_package_validate_accepts_manifest(tmp_path: Path):
    path = tmp_path / "modelable.package.toml"
    _write_manifest(path)

    result = CliRunner().invoke(cli, ["package", "validate", str(path)])

    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_package_inspect_emits_normalized_json(tmp_path: Path):
    path = tmp_path / "modelable.package.toml"
    _write_manifest(path)

    result = CliRunner().invoke(cli, ["package", "inspect", str(path), "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["package"]["name"] == "customer.contracts"


def test_package_validate_rejects_invalid_manifest(tmp_path: Path):
    path = tmp_path / "modelable.package.toml"
    path.write_text("[package]\nname = 'bad name'\nversion = '1.0.0'\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["package", "validate", str(path)])

    assert result.exit_code == 1
    assert "invalid package name" in result.output


def test_package_artifact_commands_pack_verify_and_unpack(tmp_path: Path):
    manifest = tmp_path / "modelable.package.toml"
    _write_manifest(manifest)
    snapshot = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(FIXTURE), snapshot, package_manifest_path=manifest)
    artifact = tmp_path / "customer.modelable-package"
    unpacked = tmp_path / "unpacked"

    packed = CliRunner().invoke(
        cli,
        ["package", "pack", str(manifest), "--snapshot", str(snapshot), "--out", str(artifact)],
    )
    verified = CliRunner().invoke(cli, ["package", "verify", str(artifact)])
    unpack_result = CliRunner().invoke(cli, ["package", "unpack", str(artifact), "--out", str(unpacked)])

    assert packed.exit_code == 0, packed.output
    assert verified.exit_code == 0, verified.output
    assert unpack_result.exit_code == 0, unpack_result.output
    assert (unpacked / "manifest.json").exists()
