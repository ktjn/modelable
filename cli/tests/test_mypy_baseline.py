from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / ".github" / "scripts" / "check_mypy_baseline.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_mypy_baseline", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _python_command(source: str, exit_code: int = 1) -> list[str]:
    return [
        sys.executable,
        "-c",
        f"import sys; print({source!r}); raise SystemExit({exit_code})",
    ]


def test_mypy_baseline_passes_when_current_errors_are_known(tmp_path: Path) -> None:
    script = _load_script()
    baseline = tmp_path / "mypy-baseline.txt"
    baseline.write_text(
        "\n".join(
            [
                "src/modelable/a.py:1: error: first known error  [misc]",
                "src/modelable/b.py:2: error: resolved old error  [misc]",
            ]
        ),
        encoding="utf-8",
    )

    result = script.main(
        [
            "--baseline",
            str(baseline),
            "--",
            *_python_command("src\\\\modelable\\\\a.py:1: error: first known error  [misc]"),
        ]
    )

    assert result == 0


def test_mypy_baseline_fails_on_new_errors(tmp_path: Path, capsys: object) -> None:
    script = _load_script()
    baseline = tmp_path / "mypy-baseline.txt"
    baseline.write_text("src/modelable/a.py:1: error: first known error  [misc]\n", encoding="utf-8")

    result = script.main(
        [
            "--baseline",
            str(baseline),
            "--",
            *_python_command(
                "\n".join(
                    [
                        "src/modelable/a.py:1: error: first known error  [misc]",
                        "src/modelable/new.py:3: error: new regression  [arg-type]",
                    ]
                )
            ),
        ]
    )
    captured = capsys.readouterr()

    assert result == 1
    assert "new mypy errors beyond baseline" in captured.out
    assert "src/modelable/new.py:3: error: new regression  [arg-type]" in captured.out


def test_mypy_baseline_surfaces_non_mypy_command_failures(tmp_path: Path, capsys: object) -> None:
    script = _load_script()
    baseline = tmp_path / "mypy-baseline.txt"
    baseline.write_text("", encoding="utf-8")

    result = script.main(
        [
            "--baseline",
            str(baseline),
            "--",
            sys.executable,
            "-c",
            "import sys; print('tool exploded'); raise SystemExit(7)",
        ]
    )
    captured = capsys.readouterr()

    assert result == 7
    assert "mypy command failed without parseable error lines" in captured.out
    assert "tool exploded" in captured.out


def test_mypy_baseline_script_exits_with_main_result() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
