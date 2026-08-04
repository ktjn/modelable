from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

_TOLERANCE_PERCENT = 0.1


def _parse_coverage_xml(path: Path) -> dict[str, float]:
    tree = ElementTree.parse(path)
    rates: dict[str, float] = {}
    for element in tree.getroot().iter("class"):
        filename = element.get("filename")
        line_rate = element.get("line-rate")
        if filename is None or line_rate is None:
            continue
        rates[filename.replace("\\", "/")] = float(line_rate) * 100
    return rates


def _read_baseline(path: Path) -> dict[str, float]:
    baseline: dict[str, float] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        filename, _, percent = line.partition(":")
        baseline[filename.strip()] = float(percent.strip().rstrip("%"))
    return baseline


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when a critical-path module's test coverage drops below its checked-in baseline."
    )
    parser.add_argument("--coverage-xml", required=True, type=Path, help="Path to a coverage.py Cobertura XML report.")
    parser.add_argument("--baseline", required=True, type=Path, help="Path to the checked-in coverage baseline.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    if not args.coverage_xml.exists():
        print(f"coverage report not found: {args.coverage_xml}")
        return 1

    current = _parse_coverage_xml(args.coverage_xml)
    baseline = _read_baseline(args.baseline)

    missing: list[str] = []
    regressions: list[tuple[str, float, float]] = []
    improved: list[tuple[str, float, float]] = []
    for filename, minimum in sorted(baseline.items()):
        actual = current.get(filename)
        if actual is None:
            missing.append(filename)
            continue
        if actual < minimum - _TOLERANCE_PERCENT:
            regressions.append((filename, actual, minimum))
        elif actual > minimum + _TOLERANCE_PERCENT:
            improved.append((filename, actual, minimum))

    if missing:
        print(f"{len(missing)} critical-path file(s) missing from the coverage report:")
        for filename in missing:
            print(f"  {filename}")

    if regressions:
        print(f"{len(regressions)} critical-path file(s) below their coverage baseline:")
        for filename, actual, minimum in regressions:
            print(f"  {filename}: {actual:.2f}% (baseline: {minimum:.2f}%)")

    if missing or regressions:
        return 1

    print(f"critical-path coverage ratchet passed: {len(baseline)} files checked, {len(improved)} improved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
