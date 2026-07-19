from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from email.parser import BytesParser
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from zipfile import ZipFile

BUILD_SCRIPT = Path(__file__).parents[1] / "scripts" / "build_browser_wheel.py"
SPEC = spec_from_file_location("build_browser_wheel", BUILD_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BUILD_BROWSER_WHEEL = module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_BROWSER_WHEEL)

build_browser_wheel = BUILD_BROWSER_WHEEL.build_browser_wheel
scan_forbidden_imports = BUILD_BROWSER_WHEEL.scan_forbidden_imports
selected_source_paths = BUILD_BROWSER_WHEEL.selected_source_paths

FORBIDDEN_IMPORTS = {
    "click",
    "rich",
    "pygls",
    "lsprotocol",
    "psycopg",
    "psycopg_binary",
    "socket",
    "subprocess",
}
EXPECTED_DEPENDENCIES = [
    "jsonschema==4.26.0",
    "lark==1.3.1",
    "pydantic==2.12.5",
    "pyyaml==6.0.3",
    "referencing==0.37.0",
]


def test_browser_module_selection_excludes_desktop_surfaces() -> None:
    selected = {path.as_posix() for path in selected_source_paths()}
    assert "modelable/browser/api.py" in selected
    assert "modelable/grammar/modelable.lark" in selected
    assert not any(path.startswith("modelable/commands/") for path in selected)
    assert not any(path.startswith("modelable/lsp/") for path in selected)
    assert not any(path.startswith("modelable/runtime/") for path in selected)
    assert "modelable/cli.py" not in selected


def test_browser_module_selection_excludes_interpreter_caches() -> None:
    selected = selected_source_paths()
    assert not any("__pycache__" in path.parts for path in selected)
    assert not any(path.suffix in {".pyc", ".pyo"} for path in selected)


def test_forbidden_import_scan_reports_exact_module(tmp_path: Path) -> None:
    source = tmp_path / "bad.py"
    source.write_text("from psycopg import connect\n", encoding="utf-8")
    assert scan_forbidden_imports([source]) == [(source, 1, "psycopg")]


def test_browser_build_backend_is_exactly_constrained() -> None:
    browser_root = Path(__file__).parents[1] / "browser"
    with (browser_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    assert pyproject["build-system"]["requires"] == ["hatchling==1.31.0"]
    assert (browser_root / "build-constraints.txt").read_text(encoding="utf-8") == ("hatchling==1.31.0\n")


def test_browser_wheel_contains_only_browser_compiler_surface(tmp_path: Path) -> None:
    wheel_path = build_browser_wheel(tmp_path)

    with ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(wheel.read(metadata_name))

    assert metadata["Name"] == "modelable-browser"
    assert metadata["Requires-Python"] == "<3.15,>=3.14"
    requirements = metadata.get_all("Requires-Dist", [])
    assert not any(
        re.split(r"[\s\[\]()<>=!~;]", requirement, maxsplit=1)[0].lower() in FORBIDDEN_IMPORTS
        for requirement in requirements
    )
    assert "modelable/browser/api.py" in names
    assert "modelable/grammar/modelable.lark" in names
    assert not any(name.startswith("modelable/commands/") for name in names)
    assert not any(name.startswith("modelable/lsp/") for name in names)
    assert not any(name.startswith("modelable/runtime/") for name in names)
    assert "modelable/cli.py" not in names


def test_repeated_clean_browser_wheels_are_byte_identical_and_auditable(
    tmp_path: Path,
) -> None:
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    first_wheel = build_browser_wheel(first_output)
    second_wheel = build_browser_wheel(second_output)

    assert first_wheel.read_bytes() == second_wheel.read_bytes()
    first_manifest = json.loads((first_output / "browser-manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second_output / "browser-manifest.json").read_text(encoding="utf-8"))
    assert first_manifest == second_manifest
    assert first_manifest["sha256"] == hashlib.sha256(first_wheel.read_bytes()).hexdigest()
    assert (
        first_manifest["commit"]
        == subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parents[2],
            text=True,
        ).strip()
    )

    with ZipFile(first_wheel) as wheel:
        metadata_name = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(wheel.read(metadata_name))
    assert sorted(metadata.get_all("Requires-Dist", [])) == EXPECTED_DEPENDENCIES

    audit = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys\n"
                f"sys.path.insert(0, {str(first_wheel)!r})\n"
                "import modelable.browser as browser\n"
                "import modelable.registry as registry\n"
                "assert browser.BrowserCompiler\n"
                "assert browser.dispatch_browser_request\n"
                "assert 'build_registry' not in registry.__all__\n"
                "try:\n"
                "    registry.build_registry\n"
                "except AttributeError as error:\n"
                "    assert str(error) == "
                "'modelable.registry.build_registry is unavailable in the browser wheel'\n"
                "else:\n"
                "    raise AssertionError('build_registry was unexpectedly advertised')\n"
            ),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert audit.returncode == 0, audit.stderr
