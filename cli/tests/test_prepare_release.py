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
