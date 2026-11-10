#!/usr/bin/env python3
"""Run TLC formal verification against Modelable TLA+ specifications.

Validates the pinned tla2tools.jar release against its expected SHA-256 hash,
executes TLC with isolated state storage outside the workspace, and fails
if any invariant or property is violated.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PINNED_TLA2TOOLS_URL = (
    "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
)
PINNED_TLA2TOOLS_SHA256 = (
    "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
)


def verify_sha256(path: Path, expected_hash: str) -> bool:
    """Return True if path matches the expected SHA-256 hex digest."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hash.lower()


def resolve_tla2tools_jar(candidate_path: Path | None) -> Path:
    """Find, verify, or download the pinned tla2tools.jar."""
    if candidate_path and candidate_path.is_file():
        if verify_sha256(candidate_path, PINNED_TLA2TOOLS_SHA256):
            return candidate_path
        raise RuntimeError(
            f"Candidate jar {candidate_path} does not match expected SHA-256 {PINNED_TLA2TOOLS_SHA256}"
        )

    env_path = os.environ.get("TLA2TOOLS_JAR")
    if env_path:
        p = Path(env_path)
        if p.is_file() and verify_sha256(p, PINNED_TLA2TOOLS_SHA256):
            return p
        raise RuntimeError(
            f"TLA2TOOLS_JAR={env_path} is missing or has incorrect SHA-256"
        )

    # Local repository cache fallback
    repo_root = Path(__file__).resolve().parent.parent.parent
    local_cache = repo_root / ".agentbuild" / "formal" / "tla2tools.jar"
    if local_cache.is_file() and verify_sha256(local_cache, PINNED_TLA2TOOLS_SHA256):
        return local_cache

    # Download to user cache
    cache_dir = Path.home() / ".cache" / "modelable" / "formal"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_jar = cache_dir / "tla2tools-1.7.4.jar"
    if cached_jar.is_file() and verify_sha256(cached_jar, PINNED_TLA2TOOLS_SHA256):
        return cached_jar

    print(
        f"Downloading pinned tla2tools.jar from {PINNED_TLA2TOOLS_URL} ...",
        file=sys.stderr,
    )
    urllib.request.urlretrieve(PINNED_TLA2TOOLS_URL, cached_jar)
    if not verify_sha256(cached_jar, PINNED_TLA2TOOLS_SHA256):
        cached_jar.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded tla2tools.jar did not match expected SHA-256 {PINNED_TLA2TOOLS_SHA256}"
        )
    return cached_jar


def run_tlc(
    jar_path: Path,
    model_path: Path,
    config_path: Path,
    timeout_seconds: int = 120,
) -> int:
    """Run TLC model checker with state isolated in a temporary directory."""
    with tempfile.TemporaryDirectory(prefix="modelable-tlc-") as temp_metadir:
        cmd = [
            "java",
            "-XX:+UseParallelGC",
            "-cp",
            str(jar_path),
            "tlc2.TLC",
            "-metadir",
            temp_metadir,
            "-config",
            str(config_path.resolve()),
            str(model_path.resolve()),
        ]

        print(f"Running TLC: {' '.join(cmd)}", flush=True)
        proc = subprocess.run(
            cmd,
            cwd=model_path.parent,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)

        if proc.returncode != 0:
            print(f"\nTLC failed with exit code {proc.returncode}", file=sys.stderr)
            return proc.returncode

        print("\nTLC verification completed successfully: all invariants hold.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TLC formal verification on Modelable specifications."
    )
    parser.add_argument(
        "--jar",
        type=Path,
        default=None,
        help="Path to pinned tla2tools.jar",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("formal/tla/ModelLifecycle.tla"),
        help="Path to .tla specification",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("formal/tla/ModelLifecycle.cfg"),
        help="Path to .cfg configuration",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Maximum runtime budget in seconds",
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent
    model_path = (repo_root / args.model).resolve()
    config_path = (repo_root / args.config).resolve()

    if not model_path.is_file():
        print(f"Model file not found: {model_path}", file=sys.stderr)
        return 1
    if not config_path.is_file():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        jar = resolve_tla2tools_jar(
            (repo_root / args.jar).resolve() if args.jar else None
        )
    except Exception as exc:
        print(f"Error resolving tla2tools.jar: {exc}", file=sys.stderr)
        return 1

    return run_tlc(jar, model_path, config_path, timeout_seconds=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
