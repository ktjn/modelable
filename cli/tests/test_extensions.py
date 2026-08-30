from __future__ import annotations

import pytest

from modelable.extensions import ExtensionDescriptorError, parse_extension_descriptor


def test_extension_descriptor_round_trips_canonical_payload() -> None:
    descriptor = parse_extension_descriptor(
        {
            "protocol": "modelable.extension/v1",
            "id": "example.sql",
            "version": "1.2.3",
            "accepted_plan_versions": ["modelable.plan/v0"],
            "capabilities": ["records", "lineage"],
            "configuration_schema": "modelable/schemas/example.json",
            "output_kinds": ["artifact"],
            "compatibility_support": True,
        }
    )

    assert descriptor.as_dict() == {
        "protocol": "modelable.extension/v1",
        "id": "example.sql",
        "version": "1.2.3",
        "accepted_plan_versions": ["modelable.plan/v0"],
        "capabilities": ["lineage", "records"],
        "configuration_schema": "modelable/schemas/example.json",
        "output_kinds": ["artifact"],
        "compatibility_support": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"protocol": "modelable.extension/v2"},
        {"protocol": "modelable.extension/v1", "id": "example"},
        {
            "protocol": "modelable.extension/v1",
            "id": "example",
            "version": "1",
            "accepted_plan_versions": [],
            "capabilities": [],
            "configuration_schema": None,
            "output_kinds": [],
            "compatibility_support": False,
            "extra": True,
        },
    ],
)
def test_extension_descriptor_rejects_invalid_payload(payload: dict[str, object]) -> None:
    with pytest.raises(ExtensionDescriptorError):
        parse_extension_descriptor(payload)


def test_extension_descriptor_rejects_unknown_capabilities() -> None:
    payload = {
        "protocol": "modelable.extension/v1",
        "id": "example.target",
        "version": "1.0.0",
        "accepted_plan_versions": ["modelable.plan/v0"],
        "capabilities": ["not-a-standard-capability"],
        "configuration_schema": None,
        "output_kinds": ["artifact"],
        "compatibility_support": False,
    }

    with pytest.raises(ExtensionDescriptorError, match="unknown capability"):
        parse_extension_descriptor(payload)
