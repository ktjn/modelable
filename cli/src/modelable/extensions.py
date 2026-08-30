"""Validated, JSON-compatible extension descriptors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PROTOCOL = "modelable.extension/v1"


class ExtensionDescriptorError(ValueError):
    """Raised when an extension descriptor does not satisfy its protocol."""


@dataclass(frozen=True)
class ExtensionDescriptor:
    protocol: str
    id: str
    version: str
    accepted_plan_versions: tuple[str, ...]
    capabilities: tuple[str, ...]
    configuration_schema: str | None
    output_kinds: tuple[str, ...]
    compatibility_support: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "id": self.id,
            "version": self.version,
            "accepted_plan_versions": list(self.accepted_plan_versions),
            "capabilities": list(self.capabilities),
            "configuration_schema": self.configuration_schema,
            "output_kinds": list(self.output_kinds),
            "compatibility_support": self.compatibility_support,
        }


def parse_extension_descriptor(data: Mapping[str, Any]) -> ExtensionDescriptor:
    """Validate and normalize one modelable.extension/v1 descriptor."""
    if not isinstance(data, Mapping):
        raise ExtensionDescriptorError("extension descriptor must be an object")
    required = {
        "protocol",
        "id",
        "version",
        "accepted_plan_versions",
        "capabilities",
        "configuration_schema",
        "output_kinds",
        "compatibility_support",
    }
    unknown = sorted(set(data) - required)
    missing = sorted(required - set(data))
    if unknown:
        raise ExtensionDescriptorError(f"unknown descriptor key(s): {', '.join(unknown)}")
    if missing:
        raise ExtensionDescriptorError(f"missing descriptor key(s): {', '.join(missing)}")
    if data["protocol"] != PROTOCOL:
        raise ExtensionDescriptorError(f"descriptor protocol must be {PROTOCOL!r}")
    protocol = data["protocol"]
    descriptor_id = data["id"]
    version = data["version"]
    configuration_schema = data["configuration_schema"]
    compatibility_support = data["compatibility_support"]
    if not isinstance(protocol, str) or not isinstance(descriptor_id, str) or not descriptor_id:
        raise ExtensionDescriptorError("descriptor protocol and id must be non-empty strings")
    if not isinstance(version, str) or not version:
        raise ExtensionDescriptorError("descriptor version must be a non-empty string")
    if configuration_schema is not None and (not isinstance(configuration_schema, str) or not configuration_schema):
        raise ExtensionDescriptorError("configuration_schema must be a non-empty string or null")
    if not isinstance(compatibility_support, bool):
        raise ExtensionDescriptorError("compatibility_support must be a boolean")
    return ExtensionDescriptor(
        protocol=protocol,
        id=descriptor_id,
        version=version,
        accepted_plan_versions=_string_sequence(data["accepted_plan_versions"], "accepted_plan_versions"),
        capabilities=_string_sequence(data["capabilities"], "capabilities"),
        configuration_schema=configuration_schema,
        output_kinds=_string_sequence(data["output_kinds"], "output_kinds"),
        compatibility_support=compatibility_support,
    )


def _string_sequence(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ExtensionDescriptorError(f"{field} must be an array of non-empty strings")
    if len(set(value)) != len(value):
        raise ExtensionDescriptorError(f"{field} must not contain duplicates")
    return tuple(sorted(value))
