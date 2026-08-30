from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest

from modelable.artifact_manifest import _compiler_version
from modelable.emitters.targets import get_codegen_target
from modelable.extensions import (
    PROTOCOL,
    ExtensionDescriptor,
    ExtensionDescriptorError,
    parse_extension_descriptor,
    parse_extension_pin,
    pin_extension_descriptor,
    validate_extension_pin,
)


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


def test_target_descriptor_and_manifest_share_package_version_fallback() -> None:
    with patch("modelable.extensions.version", side_effect=PackageNotFoundError):
        descriptor_version = get_codegen_target("typescript").extension_descriptor().version
        assert descriptor_version == _compiler_version()


def test_extension_pin_round_trips_identity_hash_and_protocol() -> None:
    descriptor = ExtensionDescriptor(
        protocol=PROTOCOL,
        id="example.target",
        version="1.2.3",
        accepted_plan_versions=("modelable.plan/v0",),
        capabilities=("records",),
        configuration_schema=None,
        output_kinds=("artifact",),
        compatibility_support=False,
    )

    pin = pin_extension_descriptor(descriptor, "a" * 64, source="oci://example/target")

    assert pin.as_dict() == {
        "accepted_protocol_versions": [PROTOCOL],
        "id": "example.target",
        "implementation_hash": "a" * 64,
        "source": "oci://example/target",
        "version": "1.2.3",
    }
    assert parse_extension_pin(pin.as_dict()) == pin
    validate_extension_pin(descriptor, pin)


@pytest.mark.parametrize(
    "field, value",
    [
        ("id", ""),
        ("version", ""),
        ("implementation_hash", "not-a-sha256"),
        ("accepted_protocol_versions", []),
        ("source", "https://user:password@example.com/target"),
        ("source", "oci://example/target?access_token=redacted"),
        ("source", "oci://example/target?PASSWORD=redacted"),
    ],
)
def test_extension_pin_rejects_invalid_fields(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "id": "example.target",
        "version": "1.2.3",
        "implementation_hash": "a" * 64,
        "source": None,
        "accepted_protocol_versions": [PROTOCOL],
    }
    payload[field] = value

    with pytest.raises(ExtensionDescriptorError):
        parse_extension_pin(payload)


def test_extension_pin_rejects_descriptor_identity_or_protocol_mismatch() -> None:
    descriptor = ExtensionDescriptor(
        protocol=PROTOCOL,
        id="example.target",
        version="1.2.3",
        accepted_plan_versions=("modelable.plan/v0",),
        capabilities=("records",),
        configuration_schema=None,
        output_kinds=("artifact",),
        compatibility_support=False,
    )
    pin = parse_extension_pin(
        {
            "id": "other.target",
            "version": "1.2.3",
            "implementation_hash": "a" * 64,
            "source": None,
            "accepted_protocol_versions": [PROTOCOL],
        }
    )

    with pytest.raises(ExtensionDescriptorError, match="identity"):
        validate_extension_pin(descriptor, pin)


def test_extension_pin_rejects_credential_bearing_source() -> None:
    descriptor = ExtensionDescriptor(
        protocol=PROTOCOL,
        id="example.target",
        version="1.2.3",
        accepted_plan_versions=("modelable.plan/v0",),
        capabilities=("records",),
        configuration_schema=None,
        output_kinds=("artifact",),
        compatibility_support=False,
    )

    with pytest.raises(ExtensionDescriptorError, match="credentials"):
        pin_extension_descriptor(descriptor, "a" * 64, source="https://user:password@example.com/target")
