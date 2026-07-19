from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "run_browser_playground.py"
EXPECTED_NPM_CMD_CALLS = [
    ("cli", ("uv", "run", "ruff", "check", ".")),
    ("cli", ("uv", "run", "ruff", "format", "--check", ".")),
    (
        "cli",
        (
            "uv",
            "run",
            "python",
            "../.github/scripts/check_mypy_baseline.py",
            "--baseline",
            "mypy-baseline.txt",
            "--",
            "uv",
            "run",
            "mypy",
            "src/modelable",
            "--no-error-summary",
            "--show-error-codes",
        ),
    ),
    ("cli", ("uv", "run", "pytest", "--tb=short")),
    ("web", ("npm.cmd", "ci")),
    ("web", ("npm.cmd", "run", "check")),
    ("web", ("npm.cmd", "test")),
    ("web", ("npm.cmd", "run", "build")),
    ("web", ("npm.cmd", "run", "test:e2e")),
    ("web", ("npm.cmd", "run", "check:budgets")),
]


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_browser_playground", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runs_every_command_in_order_with_platform_safe_argv() -> None:
    module = _load_runner()
    calls: list[tuple[tuple[str, ...], Path, bool]] = []

    def fake_run(command: Sequence[str], *, cwd: Path, check: bool) -> None:
        assert isinstance(command, list)
        calls.append((tuple(command), cwd, check))

    module.run_commands(
        repo_root=SCRIPT.parents[2],
        runner=fake_run,
        npm_executable="npm.cmd",
    )

    expected = [(command, SCRIPT.parents[2] / directory, True) for directory, command in EXPECTED_NPM_CMD_CALLS]
    assert calls == expected


def test_skip_install_omits_only_npm_ci() -> None:
    module = _load_runner()
    calls: list[tuple[str, ...]] = []

    def fake_run(command: Sequence[str], *, cwd: Path, check: bool) -> None:
        calls.append(tuple(command))

    module.run_commands(
        repo_root=SCRIPT.parents[2],
        runner=fake_run,
        npm_executable="npm",
        skip_install=True,
    )

    assert ("npm", "ci") not in calls
    assert calls[-1] == ("npm", "run", "check:budgets")
    assert len(calls) == len(module.COMMANDS) - 1


def test_stops_immediately_when_a_command_fails() -> None:
    module = _load_runner()
    calls: list[tuple[tuple[str, ...], Path, bool]] = []

    def fake_run(command: Sequence[str], *, cwd: Path, check: bool) -> None:
        calls.append((tuple(command), cwd, check))
        if len(calls) == 3:
            raise subprocess.CalledProcessError(1, command)

    with pytest.raises(subprocess.CalledProcessError):
        module.run_commands(
            repo_root=SCRIPT.parents[2],
            runner=fake_run,
            npm_executable="npm.cmd",
        )

    expected = [(command, SCRIPT.parents[2] / directory, True) for directory, command in EXPECTED_NPM_CMD_CALLS]
    assert calls == expected[:3]
    assert not any(call in calls for call in expected[3:])


def test_resolves_npm_cmd_with_shutil_which_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_runner()
    lookups: list[str] = []

    def fake_which(executable: str) -> str:
        lookups.append(executable)
        return "C:\\Program Files\\nodejs\\npm.cmd"

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.shutil, "which", fake_which)

    assert module.resolve_npm_executable() == "C:\\Program Files\\nodejs\\npm.cmd"
    assert lookups == ["npm.cmd"]
