from __future__ import annotations

import importlib.util
import json
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from modelable.release import build_release_manifest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "run_release_preflight.py"
REPO_ROOT = Path(__file__).parents[2]


def _load_preflight() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_release_preflight", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _assemble_complete_release(dist_dir: Path, *, package_version: str = "1.2.3") -> None:
    dist_dir.mkdir(parents=True, exist_ok=True)
    _write(dist_dir / f"modelable-{package_version}-py3-none-any.whl", "wheel-bytes")
    _write(dist_dir / f"modelable-{package_version}.tar.gz", "sdist-bytes")
    _write(dist_dir / f"modelable-vscode-{package_version}.vsix", "vsix-bytes")
    build_release_manifest(
        dist_dir=dist_dir,
        commit_sha="0" * 40,
        git_tag=None,
        package_version=package_version,
        python_version="3.14",
        build_timestamp="2026-01-01T00:00:00Z",
        extension_version=package_version,
    )


def _verify(
    module: ModuleType,
    dist_dir: Path,
    *,
    package_version: str = "1.2.3",
    extension_version: str = "1.2.3",
) -> None:
    module.verify_release_inventory(
        dist_dir=dist_dir,
        package_version=package_version,
        extension_version=extension_version,
    )


def test_complete_release_inventory_passes(tmp_path: Path) -> None:
    module = _load_preflight()
    dist_dir = tmp_path / "dist"
    _assemble_complete_release(dist_dir)

    _verify(module, dist_dir)


def test_missing_wheel_is_rejected(tmp_path: Path) -> None:
    module = _load_preflight()
    dist_dir = tmp_path / "dist"
    _assemble_complete_release(dist_dir)
    (dist_dir / "modelable-1.2.3-py3-none-any.whl").unlink()

    with pytest.raises(module.PreflightError, match="wheel"):
        _verify(module, dist_dir)


def test_missing_vsix_is_rejected(tmp_path: Path) -> None:
    module = _load_preflight()
    dist_dir = tmp_path / "dist"
    _assemble_complete_release(dist_dir)
    (dist_dir / "modelable-vscode-1.2.3.vsix").unlink()

    with pytest.raises(module.PreflightError, match="VS Code extension"):
        _verify(module, dist_dir)


def test_unexpected_dist_entry_is_rejected(tmp_path: Path) -> None:
    module = _load_preflight()
    dist_dir = tmp_path / "dist"
    _assemble_complete_release(dist_dir)
    _write(dist_dir / "modelable-1.2.3.zip", "stray")

    with pytest.raises(module.PreflightError, match="unexpected"):
        _verify(module, dist_dir)


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    module = _load_preflight()
    dist_dir = tmp_path / "dist"
    _assemble_complete_release(dist_dir)
    (dist_dir / "modelable-1.2.3-py3-none-any.whl").write_text("tampered", encoding="utf-8")

    with pytest.raises(module.PreflightError, match="checksum"):
        _verify(module, dist_dir)


def test_manifest_package_version_mismatch_is_rejected(tmp_path: Path) -> None:
    module = _load_preflight()
    dist_dir = tmp_path / "dist"
    _assemble_complete_release(dist_dir, package_version="1.2.3")

    with pytest.raises(module.PreflightError, match="package version"):
        _verify(module, dist_dir, package_version="9.9.9")


def test_extension_version_mismatch_is_rejected_by_version_parity() -> None:
    module = _load_preflight()

    with pytest.raises(module.PreflightError, match="extension version"):
        module.verify_version_parity(package_version="1.2.3", extension_version="1.2.4")


def test_venv_bin_matches_platform_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_preflight()
    venv_dir = Path("venv")

    monkeypatch.setattr(module.sys, "platform", "win32")
    assert module.venv_bin(venv_dir, "python") == venv_dir / "Scripts" / "python.exe"
    assert module.venv_bin(venv_dir, "modelable") == venv_dir / "Scripts" / "modelable.exe"

    monkeypatch.setattr(module.sys, "platform", "linux")
    assert module.venv_bin(venv_dir, "python") == venv_dir / "bin" / "python"
    assert module.venv_bin(venv_dir, "modelable") == venv_dir / "bin" / "modelable"


def test_prepare_dist_directory_removes_stale_artifacts(tmp_path: Path) -> None:
    module = _load_preflight()
    dist_dir = tmp_path / "dist"
    _write(dist_dir / "modelable-0.0.1-py3-none-any.whl", "stale")

    module.prepare_dist_directory(dist_dir)

    assert dist_dir.is_dir()
    assert list(dist_dir.iterdir()) == []


def test_preflight_runs_packaging_commands_and_verifies_inventory(tmp_path: Path) -> None:
    module = _load_preflight()
    repo_root = tmp_path / "repo"
    cli_root = repo_root / "cli"
    dist_dir = cli_root / "dist"
    _write(cli_root / "pyproject.toml", '[project]\nname = "modelable"\nversion = "1.2.3"\n')
    _write(repo_root / "vscode" / "package.json", json.dumps({"version": "1.2.3"}))
    _write(repo_root / "vscode" / "modelable-vscode-1.2.3.vsix", "vsix-bytes")

    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(command: Sequence[str], *, cwd: Path, check: bool, timeout: float) -> None:
        del check, timeout
        argv = tuple(command)
        calls.append((argv, cwd))
        if argv == ("uv", "run", "python", "-m", "build"):
            _write(dist_dir / "modelable-1.2.3-py3-none-any.whl", "wheel-bytes")
            _write(dist_dir / "modelable-1.2.3.tar.gz", "sdist-bytes")
        if "modelable.release" in argv:
            build_release_manifest(
                dist_dir=dist_dir,
                commit_sha="0" * 40,
                git_tag=None,
                package_version="1.2.3",
                python_version="3.14",
                build_timestamp="2026-01-01T00:00:00Z",
                extension_version="1.2.3",
            )

    module.run_preflight(
        repo_root=repo_root,
        commit_sha="0" * 40,
        git_tag=None,
        package_version=None,
        extension_version=None,
        python_version="3.14",
        build_timestamp="2026-01-01T00:00:00Z",
        repository_url="https://github.com/ktjn/modelable",
        license_expression="Apache-2.0",
        workflow_run_url=None,
        runner=fake_run,
    )

    commands = [argv for argv, _ in calls]
    assert commands[0] == ("uv", "run", "python", "-m", "build")
    assert commands[1][:6] == ("uv", "run", "--with", "twine", "twine", "check")
    assert commands[1][6:] == (
        str(dist_dir / "modelable-1.2.3-py3-none-any.whl"),
        str(dist_dir / "modelable-1.2.3.tar.gz"),
    )
    assert commands[2][:2] == ("uv", "venv")
    assert commands[3][:3] == ("uv", "pip", "install")
    assert Path(commands[4][0]).name in {"modelable", "modelable.exe"}
    assert commands[4][1:] == ("--version",)
    assert Path(commands[5][0]).name in {"modelable", "modelable.exe"}
    assert commands[5][1:] == ("validate", "samples/mvp", "--strict")
    assert "modelable.release" in commands[6]
    assert commands[6][commands[6].index("--dist") + 1] == str(dist_dir)
    assert [cwd for _, cwd in calls] == [
        cli_root,
        cli_root,
        cli_root,
        cli_root,
        cli_root,
        repo_root,
        cli_root,
    ]
    assert (dist_dir / "modelable-vscode-1.2.3.vsix").read_text(encoding="utf-8") == "vsix-bytes"
    assert (dist_dir / "release-manifest.json").is_file()


def test_release_workflow_calls_the_shared_preflight() -> None:
    module = _load_preflight()
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    run_scripts = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if isinstance(step, dict) and "run" in step
    ]

    assert any(module.PREFLIGHT_SCRIPT_PATH in script for script in run_scripts)
    assert not any("python -m build" in script for script in run_scripts)
    assert not any("twine check" in script for script in run_scripts)
    assert not any("modelable.release" in script for script in run_scripts)
