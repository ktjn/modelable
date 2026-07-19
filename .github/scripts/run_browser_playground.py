from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

COMMANDS = (
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
    ("web", ("npm", "ci")),
    ("web", ("npm", "run", "check")),
    ("web", ("npm", "test")),
    ("web", ("npm", "run", "build")),
    ("web", ("npm", "run", "test:e2e")),
    ("web", ("npm", "run", "check:budgets")),
)

CommandRunner = Callable[..., object]


def resolve_npm_executable() -> str:
    if sys.platform != "win32":
        return "npm"
    npm = shutil.which("npm.cmd")
    if npm is None:
        raise FileNotFoundError("npm.cmd was not found on PATH")
    return npm


def run_commands(
    *,
    repo_root: Path,
    runner: CommandRunner = subprocess.run,
    npm_executable: str | None = None,
    skip_install: bool = False,
) -> None:
    npm = resolve_npm_executable() if npm_executable is None else npm_executable
    for directory, command in COMMANDS:
        if skip_install and command == ("npm", "ci"):
            continue
        argv = [npm if value == "npm" else value for value in command]
        runner(argv, cwd=repo_root / directory, check=True)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the complete browser playground gate.")
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="skip npm ci when dependencies are already installed",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    run_commands(
        repo_root=Path(__file__).resolve().parents[2],
        skip_install=args.skip_install,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
