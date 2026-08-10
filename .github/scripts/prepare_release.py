"""Bump the Modelable release version across the repository.

This script mirrors the manual steps in `docs/maintainers.md` section 8:

* rewrite the version in ``cli/pyproject.toml``,
* rewrite the version in ``vscode/package.json`` and the two top-level
  ``version`` fields of ``vscode/package-lock.json``,
* turn the ``## [Unreleased]`` changelog section into a dated release section,
  leaving a fresh, empty ``## [Unreleased]`` section above it.

It intentionally does *not* run ``uv lock``: the caller (a release workflow or
maintainer) regenerates ``cli/uv.lock`` so the ``modelable`` project entry
matches the new version.

The script is purely mechanical; callers validate the resulting diff.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

PYPROJECT_VERSION_RE = re.compile(r"^(\s*version\s*=\s*\")[^\"]+(\")\s*$", re.MULTILINE)
PACKAGE_JSON_VERSION_RE = re.compile(r'^(\s*"version"\s*:\s*")[^"]+("\s*[,}])\s*$', re.MULTILINE)

CHANGELOG_HEADING_RE = re.compile(r"^## \[unreleased\]$", re.IGNORECASE)
CHANGELOG_SECTION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\]")

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _rewrite_first(text: str, pattern: re.Pattern[str], version: str) -> str:
    """Replace the version inside the first match of ``pattern``."""
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"unrecognized version syntax; pattern {pattern.pattern!r}")
    return text[: match.start()] + f"{match.group(1)}{version}{match.group(2)}" + text[match.end() :]


def bump_pyproject(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = _rewrite_first(text, PYPROJECT_VERSION_RE, version)
    path.write_text(text, encoding="utf-8")


def bump_package_json(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = _rewrite_first(text, PACKAGE_JSON_VERSION_RE, version)
    path.write_text(text, encoding="utf-8")


def bump_package_lock(path: Path, version: str) -> None:
    """Update the two top-level ``version`` fields of a package-lock.json."""
    text = path.read_text(encoding="utf-8")
    matches = list(PACKAGE_JSON_VERSION_RE.finditer(text))
    if len(matches) < 2:
        raise ValueError(f"expected at least two version fields in {path}, found {len(matches)}")
    offset = 0
    for match in matches[:2]:
        start = match.start() + offset
        end = match.end() + offset
        replacement = f"{match.group(1)}{version}{match.group(2)}"
        text = text[:start] + replacement + text[end:]
        offset += len(replacement) - (end - start)
    path.write_text(text, encoding="utf-8")


def _rewrite_changelog_text(text: str, version: str, release_date: str) -> str:
    """Return the changelog with ``## [Unreleased]`` renamed to a dated section.

    A fresh, empty ``## [Unreleased]`` section is inserted above the dated one.
    The released body (everything under the renamed heading, up to the next
    released ``## [X]`` section) is preserved as the dated section's body.
    """
    lines = text.split("\n")
    unreleased_index = next(
        index for index, line in enumerate(lines) if CHANGELOG_HEADING_RE.match(line)
    )

    body = lines[unreleased_index + 1 :]
    body_end = next(
        (
            index
            for index, line in enumerate(body)
            if CHANGELOG_SECTION_RE.match(line) and "unreleased" not in line.lower()
        ),
        len(body),
    )
    released_body = body[:body_end]
    remainder = body[body_end:]

    # Keep the file header (everything above the Unreleased heading) and
    # everything from the next released section onward (older entries and
    # the compare-link footer); the fresh empty Unreleased section replaces
    # the old one and the released body becomes the dated section, matching
    # maintainers.md step 1.
    prefix = "\n".join(lines[:unreleased_index]).rstrip("\n")
    suffix = "\n".join(remainder).strip("\n")

    fresh_unreleased = "\n".join(
        ["## [Unreleased]", "", "### Added", "", "### Changed", "", "### Fixed"]
    )
    release_heading = f"## [{version}] - {release_date}"

    if released_body:
        saved = "\n".join(released_body).rstrip("\n")
        new_section = f"{release_heading}\n{saved}"
    else:
        new_section = release_heading

    if suffix:
        return f"{prefix}\n\n{fresh_unreleased}\n\n{new_section}\n\n{suffix}\n"
    return f"{prefix}\n\n{fresh_unreleased}\n\n{new_section}\n"


def rewrite_changelog(path: Path, version: str, release_date: str) -> None:
    path.write_text(_rewrite_changelog_text(path.read_text(encoding="utf-8"), version, release_date), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", metavar="VERSION", help="new version, e.g. 1.5.0")
    parser.add_argument("--pyproject", required=True)
    parser.add_argument("--package-json", required=True)
    parser.add_argument("--package-lock", required=True)
    parser.add_argument("--changelog", required=True)
    parser.add_argument("--release-date", default=date.today().isoformat())
    args = parser.parse_args(argv)

    version = args.version
    if not SEMVER_RE.match(version):
        print(f"error: invalid version {version!r}; expected X.Y.Z", file=sys.stderr)
        return 2

    pyproject = Path(args.pyproject)
    package_json = Path(args.package_json)
    package_lock = Path(args.package_lock)
    changelog = Path(args.changelog)

    for path in (pyproject, package_json, package_lock, changelog):
        if not path.exists():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 2

    try:
        bump_pyproject(pyproject, version)
        bump_package_json(package_json, version)
        bump_package_lock(package_lock, version)
        rewrite_changelog(changelog, version, args.release_date)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
