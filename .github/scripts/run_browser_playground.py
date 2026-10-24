from __future__ import annotations

import argparse
import os
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
    (
        "cli",
        (
            "uv",
            "run",
            "pytest",
            "--tb=short",
            "--cov=modelable",
            "--cov-report=term-missing",
            "--cov-report=xml",
        ),
    ),
    (
        "cli",
        (
            "uv",
            "run",
            "python",
            "../.github/scripts/check_coverage_ratchet.py",
            "--coverage-xml",
            "coverage.xml",
            "--baseline",
            "coverage-baseline.txt",
        ),
    ),
    (
        "cli",
        (
            "uv",
            "export",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "-o",
            "audit-requirements.txt",
        ),
    ),
    (
        "cli",
        (
            "uv",
            "run",
            "--with",
            "pip-audit",
            "pip-audit",
            "--strict",
            "--progress-spinner",
            "off",
            "-r",
            "audit-requirements.txt",
        ),
    ),
    ("web", ("npm", "ci")),
    ("web", ("npm", "run", "check")),
    ("web", ("npm", "test")),
    ("web", ("npm", "run", "build")),
    ("web", ("npm", "exec", "--", "playwright", "install", "chromium")),
    ("web", ("npm", "run", "test:e2e")),
    ("web", ("npm", "run", "check:budgets")),
    ("vscode", ("npm", "ci")),
    ("vscode", ("npm", "run", "check")),
    ("vscode", ("npm", "run", "build")),
    ("vscode", ("npm", "test")),
    ("vscode", ("npm", "run", "package")),
    ("cli", ("uv", "run", "python", "../.github/scripts/run_release_preflight.py")),
)


def external_commands() -> tuple[tuple[str, tuple[str, ...], dict[str, str]], ...]:
    fhir_jar = os.environ.get("MODELABLE_FHIR_VALIDATOR_JAR")
    if not fhir_jar:
        raise RuntimeError(
            "MODELABLE_FHIR_VALIDATOR_JAR must point to validator_cli.jar before running the local gate"
        )
    return (
        (
            "cli",
            (
                "uv",
                "run",
                "--with",
                "datacontract-cli",
                "pytest",
                "tests/test_emit_odcs.py",
                "--tb=short",
                "-q",
            ),
            {"MODELABLE_DATACONTRACT_CLI": "1"},
        ),
        (
            "cli",
            ("uv", "run", "pytest", "tests/test_openmetadata_testcontainers.py", "--tb=short", "-q"),
            {"MODELABLE_OPENMETADATA_TESTCONTAINERS": "1"},
        ),
        (
            "cli",
            ("uv", "run", "pytest", "tests/test_openlineage_testcontainers.py", "--tb=short", "-q"),
            {"MODELABLE_OPENLINEAGE_TESTCONTAINERS": "1"},
        ),
        (
            "cli",
            ("uv", "run", "pytest", "tests/test_fhir_validator.py", "--tb=short", "-q"),
            {"MODELABLE_FHIR_VALIDATOR": "1", "MODELABLE_FHIR_VALIDATOR_JAR": fhir_jar},
        ),
    )

CommandRunner = Callable[..., object]
COMMAND_TIMEOUT_SECONDS = 20 * 60


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
    include_external: bool = True,
    command_timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
) -> None:
    npm = resolve_npm_executable() if npm_executable is None else npm_executable
    for directory, command in COMMANDS:
        if skip_install and command == ("npm", "ci"):
            continue
        argv = [npm if value == "npm" else value for value in command]
        runner(
            argv,
            cwd=repo_root / directory,
            check=True,
            timeout=command_timeout_seconds,
        )
    if include_external:
        for directory, command, command_env in external_commands():
            environment = os.environ.copy()
            environment.update(command_env)
            runner(
                list(command),
                cwd=repo_root / directory,
                check=True,
                timeout=command_timeout_seconds,
                env=environment,
            )


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
