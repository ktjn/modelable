import json
from pathlib import Path

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.package_artifact import pack_package_artifact, unpack_package_artifact, verify_package_artifact
from modelable.registry.snapshot import resolve_workspace_snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def _write_manifest(path: Path) -> None:
    path.write_text(
        '[package]\nname = "customer.contracts"\nversion = "1.2.3"\n\n'
        '[exports]\ndeclarations = ["customer.Customer@1"]\n',
        encoding="utf-8",
    )


def test_pack_verify_and_unpack_round_trip_is_deterministic(tmp_path: Path) -> None:
    manifest = tmp_path / "modelable.package.toml"
    _write_manifest(manifest)
    snapshot = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(FIXTURE), snapshot, package_manifest_path=manifest)
    first = tmp_path / "first.modelable-package"
    second = tmp_path / "second.modelable-package"

    first_digest = pack_package_artifact(manifest, snapshot, first)
    second_digest = pack_package_artifact(manifest, snapshot, second)
    unpacked = tmp_path / "unpacked"
    package = verify_package_artifact(first)
    unpack_package_artifact(first, unpacked)

    assert first_digest == second_digest
    assert first.read_bytes() == second.read_bytes()
    assert package["$schema"] == "modelable.package/v1"
    assert json.loads((unpacked / "manifest.json").read_text(encoding="utf-8")) == package
    assert (unpacked / "objects" / "customer.Customer@1.json").exists()


def test_verify_rejects_corrupted_package_artifact(tmp_path: Path) -> None:
    manifest = tmp_path / "modelable.package.toml"
    _write_manifest(manifest)
    snapshot = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(FIXTURE), snapshot, package_manifest_path=manifest)
    artifact = tmp_path / "package.modelable-package"
    pack_package_artifact(manifest, snapshot, artifact)
    corrupted = artifact.read_bytes().replace(b"customer.contracts", b"customerXcontracts")
    artifact.write_bytes(corrupted)

    with pytest.raises(ValueError, match="invalid package artifact"):
        verify_package_artifact(artifact)
