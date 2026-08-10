from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / ".github" / "scripts" / "prepare_release.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_release", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHANGELOG = """\
# Changelog

Notable user-facing changes are documented here.

## [Unreleased]

### Added

- New feature.

### Changed

### Fixed

## [1.4.0] - 2026-08-08

### Added

- Old feature.

## [1.0.0] - 2026-06-28

### Added

- First stable release.

[Unreleased]: https://example.com/compare/v1.4.0...HEAD
[1.4.0]: https://example.com/compare/v1.0.0...v1.4.0
"""


def test_rewrite_changelog_preserves_older_releases_and_footer() -> None:
    script = _load_script()

    rewritten = script._rewrite_changelog_text(CHANGELOG, "1.5.0", "2026-08-10")

    assert "## [1.5.0] - 2026-08-10" in rewritten
    assert "- New feature." in rewritten
    # Older, already-released sections must survive the rewrite.
    assert "## [1.4.0] - 2026-08-08" in rewritten
    assert "- Old feature." in rewritten
    assert "## [1.0.0] - 2026-06-28" in rewritten
    assert "- First stable release." in rewritten
    # The compare-link footer must survive too.
    assert "[1.4.0]: https://example.com/compare/v1.0.0...v1.4.0" in rewritten

    # The new dated section comes before the older ones, and a fresh empty
    # Unreleased section sits above all of it.
    unreleased_pos = rewritten.index("## [Unreleased]")
    new_release_pos = rewritten.index("## [1.5.0]")
    old_release_pos = rewritten.index("## [1.4.0]")
    assert unreleased_pos < new_release_pos < old_release_pos


def test_main_bumps_both_pyprojects_in_lockstep(tmp_path: Path) -> None:
    script = _load_script()

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "modelable"\nversion = "1.4.0"\n', encoding="utf-8")
    browser_pyproject = tmp_path / "browser-pyproject.toml"
    browser_pyproject.write_text('[project]\nname = "modelable-browser"\nversion = "1.4.0"\n', encoding="utf-8")
    package_json = tmp_path / "package.json"
    package_json.write_text('{\n  "name": "modelable-vscode",\n  "version": "1.4.0"\n}\n', encoding="utf-8")
    package_lock = tmp_path / "package-lock.json"
    package_lock.write_text(
        '{\n  "name": "modelable-vscode",\n  "version": "1.4.0",\n'
        '  "packages": {\n    "": {\n      "name": "modelable-vscode",\n      "version": "1.4.0"\n    }\n  }\n}\n',
        encoding="utf-8",
    )
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")

    exit_code = script.main(
        [
            "1.5.0",
            "--pyproject",
            str(pyproject),
            "--browser-pyproject",
            str(browser_pyproject),
            "--package-json",
            str(package_json),
            "--package-lock",
            str(package_lock),
            "--changelog",
            str(changelog),
            "--release-date",
            "2026-08-10",
        ]
    )

    assert exit_code == 0
    assert 'version = "1.5.0"' in pyproject.read_text(encoding="utf-8")
    assert 'version = "1.5.0"' in browser_pyproject.read_text(encoding="utf-8")


def test_rewrite_changelog_with_empty_unreleased_body_still_keeps_history() -> None:
    script = _load_script()
    changelog = """\
## [Unreleased]

### Added

## [1.0.0] - 2026-06-28

### Added

- First stable release.
"""

    rewritten = script._rewrite_changelog_text(changelog, "1.1.0", "2026-08-10")

    assert "## [1.1.0] - 2026-08-10" in rewritten
    assert "## [1.0.0] - 2026-06-28" in rewritten
    assert "- First stable release." in rewritten
