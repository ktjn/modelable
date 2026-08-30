"""Validated, JSON-compatible extension descriptors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from modelable.compat.projection_fields import resolve_projection_field_type_and_optionality
from modelable.parser.ir import (
    ArrayType,
    EnumRefType,
    EnumType,
    FieldDef,
    FieldType,
    MapType,
    MdlFile,
    ObjectType,
    ProjectionField,
    UnionType,
)

PROTOCOL = "modelable.extension/v1"
STANDARD_CAPABILITIES = frozenset(
    {
        "records",
        "enums",
        "semantic-types",
        "maps",
        "unions",
        "constraints",
        "lineage",
        "compatibility",
    }
)


def modelable_version() -> str:
    """Return the installed package version used by compiler metadata."""
    try:
        return version("modelable")
    except PackageNotFoundError:
        return "development"


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
    capabilities = _string_sequence(data["capabilities"], "capabilities")
    unknown_capabilities = sorted(set(capabilities) - STANDARD_CAPABILITIES)
    if unknown_capabilities:
        raise ExtensionDescriptorError(
            f"descriptor advertises unknown capability '{unknown_capabilities[0]}'"
            if len(unknown_capabilities) == 1
            else f"descriptor advertises unknown capabilities: {', '.join(unknown_capabilities)}"
        )
    return ExtensionDescriptor(
        protocol=protocol,
        id=descriptor_id,
        version=version,
        accepted_plan_versions=_string_sequence(data["accepted_plan_versions"], "accepted_plan_versions"),
        capabilities=capabilities,
        configuration_schema=configuration_schema,
        output_kinds=_string_sequence(data["output_kinds"], "output_kinds"),
        compatibility_support=compatibility_support,
    )


def required_capabilities(mdl: MdlFile) -> tuple[str, ...]:
    """Return standard capabilities required by the normalized model."""
    required: set[str] = set()

    def visit(field_type: FieldType, field: FieldDef | ProjectionField | None = None) -> None:
        if isinstance(field_type, (EnumType, EnumRefType)):
            required.add("enums")
        elif isinstance(field_type, MapType):
            required.add("maps")
            visit(field_type.key, field)
            visit(field_type.value, field)
        elif isinstance(field_type, ArrayType):
            visit(field_type.item, field)
        elif isinstance(field_type, ObjectType):
            required.add("records")
            for nested in field_type.fields:
                visit(nested.type, nested)
        elif isinstance(field_type, UnionType):
            required.add("unions")
            for variant in field_type.variants:
                visit(variant.type, field)
        if field is not None and field.constraints:
            required.add("constraints")

    for domain in mdl.domains:
        for model_versions in domain.models.values():
            for model_version in model_versions:
                required.add("records")
                for model_field in model_version.fields:
                    visit(model_field.type, model_field)
        for projection_versions in domain.projections.values():
            for projection_version in projection_versions:
                required.add("records")
                for projection_field in projection_version.fields:
                    field_type, _ = resolve_projection_field_type_and_optionality(
                        projection_field, projection_version, mdl
                    )
                    if field_type is not None:
                        visit(field_type, projection_field)
        for semantic_type in domain.semantic_types:
            required.add("semantic-types")
            visit(semantic_type.underlying)

    return tuple(sorted(required))


def validate_extension_capabilities(descriptor: ExtensionDescriptor, mdl: MdlFile) -> None:
    """Reject normalized model requirements absent from an extension descriptor."""
    unknown = sorted(set(descriptor.capabilities) - STANDARD_CAPABILITIES)
    if unknown:
        raise ExtensionDescriptorError(
            f"descriptor advertises unknown capability '{unknown[0]}'"
            if len(unknown) == 1
            else f"descriptor advertises unknown capabilities: {', '.join(unknown)}"
        )
    missing = sorted(set(required_capabilities(mdl)) - set(descriptor.capabilities))
    if missing:
        raise ExtensionDescriptorError(
            f"target '{descriptor.id}' does not support required capability '{missing[0]}'"
            if len(missing) == 1
            else f"target '{descriptor.id}' does not support required capabilities: {', '.join(missing)}"
        )


def _string_sequence(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ExtensionDescriptorError(f"{field} must be an array of non-empty strings")
    if len(set(value)) != len(value):
        raise ExtensionDescriptorError(f"{field} must not contain duplicates")
    return tuple(sorted(value))
