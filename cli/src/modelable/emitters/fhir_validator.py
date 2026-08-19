from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from modelable.emitters.fhir import FHIR_R4_VERSION

RunCallable = Callable[..., subprocess.CompletedProcess[str]]


def validate_fhir_profile(
    profile: Path | list[Path],
    validator_jar: Path,
    *,
    java: str = "java",
    fhir_version: str = FHIR_R4_VERSION,
    run: RunCallable = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    profiles = profile if isinstance(profile, list) else [profile]
    command = [
        java,
        "-jar",
        str(validator_jar),
        *(str(p) for p in profiles),
        "-version",
        fhir_version,
    ]
    return run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
