from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / ".github" / "scripts" / "check_coverage_ratchet.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_coverage_ratchet", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_coverage_xml(path: Path, rates: dict[str, float]) -> None:
    classes = "\n".join(
        f'<class name="{Path(filename).name}" filename="{filename}" line-rate="{rate / 100}" branch-rate="0"><lines/></class>'
        for filename, rate in rates.items()
    )
    path.write_text(
        textwrap.dedent(f"""\
            <?xml version="1.0" ?>
            <coverage version="7.14.1" line-rate="0.9">
              <packages>
                <package name="src.modelable" line-rate="0.9">
                  <classes>
                    {classes}
                  </classes>
                </package>
              </packages>
            </coverage>
            """),
        encoding="utf-8",
    )


def _write_baseline(path: Path, minimums: dict[str, float]) -> None:
    lines = [f"{filename}: {minimum}" for filename, minimum in minimums.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_coverage_ratchet_passes_when_all_files_meet_baseline(tmp_path: Path) -> None:
    script = _load_script()
    coverage_xml = tmp_path / "coverage.xml"
    baseline = tmp_path / "coverage-baseline.txt"
    _write_coverage_xml(coverage_xml, {"src/modelable/compat/checker.py": 93.64})
    _write_baseline(baseline, {"src/modelable/compat/checker.py": 93.64})

    result = script.main(["--coverage-xml", str(coverage_xml), "--baseline", str(baseline)])

    assert result == 0


def test_coverage_ratchet_fails_on_regression(tmp_path: Path, capsys: object) -> None:
    script = _load_script()
    coverage_xml = tmp_path / "coverage.xml"
    baseline = tmp_path / "coverage-baseline.txt"
    _write_coverage_xml(coverage_xml, {"src/modelable/compat/checker.py": 80.0})
    _write_baseline(baseline, {"src/modelable/compat/checker.py": 93.64})

    result = script.main(["--coverage-xml", str(coverage_xml), "--baseline", str(baseline)])
    captured = capsys.readouterr()

    assert result == 1
    assert "src/modelable/compat/checker.py" in captured.out
    assert "80.00" in captured.out
    assert "93.64" in captured.out


def test_coverage_ratchet_fails_when_baseline_file_missing_from_report(tmp_path: Path, capsys: object) -> None:
    script = _load_script()
    coverage_xml = tmp_path / "coverage.xml"
    baseline = tmp_path / "coverage-baseline.txt"
    _write_coverage_xml(coverage_xml, {"src/modelable/other.py": 100.0})
    _write_baseline(baseline, {"src/modelable/compat/checker.py": 93.64})

    result = script.main(["--coverage-xml", str(coverage_xml), "--baseline", str(baseline)])
    captured = capsys.readouterr()

    assert result == 1
    assert "src/modelable/compat/checker.py" in captured.out
    assert "missing" in captured.out.lower()


def test_coverage_ratchet_fails_when_coverage_xml_missing(tmp_path: Path, capsys: object) -> None:
    script = _load_script()
    baseline = tmp_path / "coverage-baseline.txt"
    _write_baseline(baseline, {"src/modelable/compat/checker.py": 93.64})

    result = script.main(["--coverage-xml", str(tmp_path / "does-not-exist.xml"), "--baseline", str(baseline)])
    captured = capsys.readouterr()

    assert result == 1
    assert "not found" in captured.out.lower()


def test_coverage_ratchet_ignores_small_floating_point_noise(tmp_path: Path) -> None:
    script = _load_script()
    coverage_xml = tmp_path / "coverage.xml"
    baseline = tmp_path / "coverage-baseline.txt"
    _write_coverage_xml(coverage_xml, {"src/modelable/compat/checker.py": 93.60})
    _write_baseline(baseline, {"src/modelable/compat/checker.py": 93.64})

    result = script.main(["--coverage-xml", str(coverage_xml), "--baseline", str(baseline)])

    assert result == 0


def test_coverage_ratchet_script_exits_with_main_result() -> None:
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
