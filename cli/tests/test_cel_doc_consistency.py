"""docs/language-reference.md §9 CEL vocabulary must match cel.py constants."""

import re
from pathlib import Path

from modelable.expressions.cel import (
    _AGGREGATE_FUNCTIONS,
    _NON_DETERMINISTIC_FUNCTIONS,
    _SCALAR_FUNCTIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LANGUAGE_REFERENCE = REPO_ROOT / "docs" / "language-reference.md"


def _section_93() -> str:
    text = LANGUAGE_REFERENCE.read_text(encoding="utf-8")
    match = re.search(r"### 9\.3 Functions(.*?)### 9\.4", text, re.S)
    assert match is not None, "docs §9.3 not found"
    return match.group(1)


def _backtick_words(section: str) -> set[str]:
    return set(re.findall(r"`([a-zA-Z_][a-zA-Z0-9_]*)`", section))


def test_documented_scalar_functions_match_validator() -> None:
    section = _section_93()
    # Only tokens between the two function lists belong to the function vocab.
    scalar_para = section.split("Aggregate functions")[0]
    scalar = _backtick_words(scalar_para)
    assert scalar == set(_SCALAR_FUNCTIONS)


def test_documented_aggregate_functions_match_validator() -> None:
    section = _section_93()
    aggregate_para = section.split("Aggregate functions")[1].split("`min`/`max`")[0]
    aggregate = _backtick_words(aggregate_para)
    assert aggregate == set(_AGGREGATE_FUNCTIONS)


def test_documented_non_deterministic_functions_match_validator() -> None:
    section = _section_93()
    non_deterministic_para = section.split("non-deterministic:")[1]
    non_deterministic = _backtick_words(non_deterministic_para)
    assert non_deterministic == set(_NON_DETERMINISTIC_FUNCTIONS)
