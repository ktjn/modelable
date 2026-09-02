from __future__ import annotations

from pathlib import Path

import pytest

from modelable.overlays import OverlayConflictError, OverlayError, load_overlay, parse_overlay


def test_overlay_resolution_uses_documented_precedence_and_provenance() -> None:
    document = parse_overlay(
        {
            "target": "csharp",
            "version": 1,
            "defaults": {"namespace": "Contracts", "name": "default"},
            "models": {
                "customer.Customer@*": {"name": "customer"},
                "customer.Customer@>=4,<7": {"name": "versioned"},
                "customer.Customer@6": {"name": "v6"},
            },
            "fields": {
                "customer.Customer@>=4,<7#customerId": {"property_name": "CustomerId"},
                "customer.Customer@6#customerId": {"property_name": "CustomerIdV2"},
            },
        }
    )

    result = document.resolve("customer.Customer@6", "customer.Customer@6#customerId")

    assert dict(result.values) == {
        "namespace": "Contracts",
        "name": "v6",
        "property_name": "CustomerIdV2",
    }
    assert result.provenance["name"] == "customer.Customer@6"
    assert result.provenance["property_name"] == "customer.Customer@6#customerId"


def test_overlay_range_is_not_copied_to_an_unmatched_version() -> None:
    document = parse_overlay(
        {
            "target": "sql-postgres",
            "version": 1,
            "models": {"customer.Customer@>=4,<7": {"table": "customers"}},
        }
    )

    assert document.resolve("customer.Customer@3").values == {}
    assert document.resolve("customer.Customer@6").values["table"] == "customers"
    assert document.resolve("customer.Customer@7").values == {}


def test_overlay_path_wildcard_matches_one_nested_segment() -> None:
    document = parse_overlay(
        {
            "target": "csharp",
            "version": 1,
            "fields": {
                "customer.Customer@>=4,<7#address.*": {"nullable": True},
                "customer.Customer@6#address.street": {"nullable": False},
            },
        }
    )

    street = document.resolve("customer.Customer@6", "customer.Customer@6#address.street")
    city = document.resolve("customer.Customer@6", "customer.Customer@6#address.city")
    name = document.resolve("customer.Customer@6", "customer.Customer@6#name")

    assert street.values["nullable"] is False
    assert city.values["nullable"] is True
    assert name.values == {}


def test_equal_specificity_conflicts_are_rejected() -> None:
    document = parse_overlay(
        {
            "target": "sql-postgres",
            "version": 1,
            "models": {
                "customer.Customer@>=4,<7": {"table": "customers"},
                "customer.Customer@>=5,<8": {"table": "customers_v2"},
            },
        }
    )

    with pytest.raises(OverlayConflictError, match="equal-specificity"):
        document.resolve("customer.Customer@6")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"target": "sql-postgres"}, "positive integer"),
        ({"target": "sql-postgres", "version": 1, "extra": {}}, "unknown top-level"),
        ({"target": "sql-postgres", "version": 1, "models": {"Customer@1": {}}}, "invalid overlay selector"),
        ({"target": "sql-postgres", "version": 1, "fields": {"customer.Customer@1": {}}}, "requires a semantic path"),
    ],
)
def test_overlay_validation_rejects_malformed_input(data: dict[str, object], message: str) -> None:
    with pytest.raises(OverlayError, match=message):
        parse_overlay(data)


def test_overlay_loads_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "postgres.toml"
    path.write_text(
        'target = "sql-postgres"\nversion = 1\n\n[models."customer.Customer@*"]\ntable = "customers"\n',
        encoding="utf-8",
    )

    document = load_overlay(path)

    assert document.path == path
    assert document.resolve("customer.Customer@1").values["table"] == "customers"


def test_overlay_rejects_noncanonical_or_reversed_ranges() -> None:
    for selector in (
        "customer.Customer@>=4, <7",
        "customer.Customer@>=7,<4",
        "customer.Customer@>=4,<4",
        "customer.Customer@04",
        "customer.Customer@==4",
        "customer.Customer@>=4,>=7",
    ):
        with pytest.raises(OverlayError):
            parse_overlay(
                {
                    "target": "sql-postgres",
                    "version": 1,
                    "models": {selector: {"table": "customers"}},
                }
            )
