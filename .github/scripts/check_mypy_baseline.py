from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def _mypy_error_lines(output: str) -> set[str]:
    return {_normalize_line(line) for line in output.splitlines() if ": error:" in line}


def _normalize_line(line: str) -> str:
    normalized = line.strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def _read_baseline(path: Path) -> set[str]:
    return {
        _normalize_line(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail when mypy reports errors outside the checked-in baseline.")
    parser.add_argument("--baseline", required=True, type=Path, help="Path to the checked-in mypy error baseline.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after '--'.")
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("expected a mypy command after '--'")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    baseline = _read_baseline(args.baseline)
    completed = subprocess.run(
        args.command,
        check=False,
        capture_output=True,
        text=True,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    current = _mypy_error_lines(output)

    if completed.returncode != 0 and not current:
        print("mypy command failed without parseable error lines")
        print(output, end="" if output.endswith("\n") else "\n")
        return completed.returncode

    new_errors = sorted(current - baseline)
    resolved_errors = sorted(baseline - current)

    if new_errors:
        print(f"{len(new_errors)} new mypy errors beyond baseline:")
        for error in new_errors:
            print(error)
        return 1

    print(
        f"mypy baseline ratchet passed: {len(current)} current errors, {len(resolved_errors)} resolved baseline errors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
