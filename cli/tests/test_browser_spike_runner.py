from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "run_browser_spike.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_browser_spike", SCRIPT)
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

    expected = [
        (
            tuple("npm.cmd" if value == "npm" else value for value in command),
            SCRIPT.parents[2] / directory,
            True,
        )
        for directory, command in module.COMMANDS
    ]
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
    calls: list[tuple[str, ...]] = []

    def fake_run(command: Sequence[str], *, cwd: Path, check: bool) -> None:
        calls.append(tuple(command))
        if len(calls) == 2:
            raise subprocess.CalledProcessError(1, command)

    with pytest.raises(subprocess.CalledProcessError):
        module.run_commands(
            repo_root=SCRIPT.parents[2],
            runner=fake_run,
            npm_executable="npm",
        )

    assert len(calls) == 2
