"""Validated, JSON-compatible extension descriptors."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from modelable.compat.projection_fields import resolve_projection_field_type_and_optionality
from modelable.parser.ir import (
    ArrayType,
    EnumProjectionDecl,
    EnumRefType,
    EnumType,
    FieldDef,
    FieldType,
    MapType,
    MdlFile,
    NamedType,
    ObjectType,
    ProjectionField,
    UnionType,
)
from modelable.registry.resolver import resolve_enum_type_ref

PROTOCOL = "modelable.extension/v1"
STANDARD_CAPABILITIES = frozenset(
    {
        "composite-keys",
        "records",
        "enums",
        "enum-projections",
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


@dataclass(frozen=True)
class ExtensionPin:
    """Immutable provenance pin for one executable extension implementation."""

    id: str
    version: str
    implementation_hash: str
    source: str | None
    accepted_protocol_versions: tuple[str, ...]
    descriptor_hash: str | None = None
    descriptor: ExtensionDescriptor | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "accepted_protocol_versions": list(self.accepted_protocol_versions),
            "id": self.id,
            "implementation_hash": self.implementation_hash,
            "source": self.source,
            "version": self.version,
        }
        if self.descriptor_hash is not None:
            payload["descriptor_hash"] = self.descriptor_hash
        if self.descriptor is not None:
            payload["descriptor"] = self.descriptor.as_dict()
        return payload


ExtensionExecutionKind = Literal["builtin", "subprocess", "wasm"]
ExtensionFilesystemAccess = Literal["none", "workspace-read"]


@dataclass(frozen=True)
class ExtensionTrustPolicy:
    """Explicit host policy for extension execution.

    Built-in extensions run with the trust level of Modelable. Third-party
    execution requires an exact pinned implementation in the corresponding
    allowlist. Network and filesystem access stay disabled unless a host opts
    in explicitly. The native WASM host consumes the explicit allowlist;
    discovery and subprocess execution remain out of scope.
    """

    allowed_subprocess_pins: tuple[ExtensionPin, ...] = ()
    allowed_wasm_pins: tuple[ExtensionPin, ...] = ()
    filesystem_access: ExtensionFilesystemAccess = "none"
    network_enabled: bool = False

    def __post_init__(self) -> None:
        for name in ("allowed_subprocess_pins", "allowed_wasm_pins"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(value, ExtensionPin) for value in values):
                raise ExtensionDescriptorError(f"{name} must contain extension pins")
            try:
                for pin in values:
                    normalized = parse_extension_pin(pin.as_dict())
                    if normalized != pin:
                        raise ExtensionDescriptorError("pin is not canonical")
            except ExtensionDescriptorError as exc:
                raise ExtensionDescriptorError(f"{name} contains an invalid extension pin: {exc}") from exc
            identities = {(pin.id, pin.version, pin.implementation_hash) for pin in values}
            if len(identities) != len(values):
                raise ExtensionDescriptorError(f"{name} must be duplicate-free")
            if tuple(sorted(values, key=_extension_pin_sort_key)) != values:
                raise ExtensionDescriptorError(f"{name} must be sorted by pin identity")
        if self.filesystem_access not in {"none", "workspace-read"}:
            raise ExtensionDescriptorError("filesystem_access must be 'none' or 'workspace-read'")
        if not isinstance(self.network_enabled, bool):
            raise ExtensionDescriptorError("network_enabled must be a boolean")

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed_subprocess_pins": [pin.as_dict() for pin in self.allowed_subprocess_pins],
            "allowed_wasm_pins": [pin.as_dict() for pin in self.allowed_wasm_pins],
            "filesystem_access": self.filesystem_access,
            "network_enabled": self.network_enabled,
        }


def authorize_extension(
    descriptor: ExtensionDescriptor,
    *,
    execution_kind: ExtensionExecutionKind,
    pin: ExtensionPin | None = None,
    policy: ExtensionTrustPolicy | None = None,
    requested_filesystem_access: ExtensionFilesystemAccess = "none",
    network_requested: bool = False,
) -> None:
    """Authorize an extension kind without discovering or executing it."""
    if policy is None:
        policy = ExtensionTrustPolicy()
    if descriptor.protocol != PROTOCOL:
        raise ExtensionDescriptorError(f"descriptor protocol must be {PROTOCOL!r}")
    if execution_kind not in {"builtin", "subprocess", "wasm"}:
        raise ExtensionDescriptorError(f"unknown extension execution kind {execution_kind!r}")
    if requested_filesystem_access not in {"none", "workspace-read"}:
        raise ExtensionDescriptorError("unknown requested filesystem access")
    if requested_filesystem_access == "workspace-read" and policy.filesystem_access != "workspace-read":
        raise ExtensionDescriptorError("requested filesystem access exceeds extension trust policy")
    if not isinstance(network_requested, bool):
        raise ExtensionDescriptorError("network_requested must be a boolean")
    if network_requested and not policy.network_enabled:
        raise ExtensionDescriptorError("requested network access exceeds extension trust policy")
    if execution_kind == "builtin":
        return
    if pin is None:
        raise ExtensionDescriptorError("third-party extension execution requires a provenance pin")
    parse_extension_pin(pin.as_dict())
    validate_extension_pin(descriptor, pin)
    allowed = policy.allowed_subprocess_pins if execution_kind == "subprocess" else policy.allowed_wasm_pins
    if pin not in allowed:
        raise ExtensionDescriptorError(
            f"extension {descriptor.id!r} is not explicitly trusted for {execution_kind} execution"
        )


def _extension_pin_sort_key(pin: ExtensionPin) -> tuple[str, str, str]:
    return pin.id, pin.version, pin.implementation_hash


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


def validate_extension_plan_version(descriptor: ExtensionDescriptor, plan_version: str) -> None:
    """Ensure an extension accepts the normalized plan protocol being supplied."""
    if descriptor.protocol != PROTOCOL:
        raise ExtensionDescriptorError(f"descriptor protocol must be {PROTOCOL!r}")
    if not isinstance(plan_version, str) or not plan_version:
        raise ExtensionDescriptorError("plan protocol version must be a non-empty string")
    if plan_version not in descriptor.accepted_plan_versions:
        raise ExtensionDescriptorError(f"extension {descriptor.id!r} does not accept plan protocol {plan_version!r}")


def validate_extension_admission(
    descriptor: ExtensionDescriptor,
    mdl: MdlFile,
    *,
    plan_version: str,
    execution_kind: ExtensionExecutionKind = "builtin",
    policy: ExtensionTrustPolicy | None = None,
    require_compatibility_support: bool = False,
) -> None:
    """Apply the compiler-owned execution, protocol, and capability gates."""
    authorize_extension(descriptor, execution_kind=execution_kind, policy=policy)
    validate_extension_plan_version(descriptor, plan_version)
    validate_extension_capabilities(descriptor, mdl)
    if not isinstance(require_compatibility_support, bool):
        raise ExtensionDescriptorError("require_compatibility_support must be a boolean")
    if require_compatibility_support and not descriptor.compatibility_support:
        raise ExtensionDescriptorError(f"extension {descriptor.id!r} does not support compatibility analysis")


def pin_extension_descriptor(
    descriptor: ExtensionDescriptor,
    implementation_hash: str,
    *,
    source: str | None = None,
) -> ExtensionPin:
    """Create a reproducibility pin for a validated extension descriptor."""
    if descriptor.protocol != PROTOCOL:
        raise ExtensionDescriptorError(f"descriptor protocol must be {PROTOCOL!r}")
    _validate_implementation_hash(implementation_hash)
    _validate_provenance_source(source)
    return ExtensionPin(
        id=descriptor.id,
        version=descriptor.version,
        implementation_hash=implementation_hash,
        source=source,
        accepted_protocol_versions=(descriptor.protocol,),
        descriptor_hash=_descriptor_hash(descriptor),
        descriptor=descriptor,
    )


def parse_extension_pin(data: Mapping[str, Any]) -> ExtensionPin:
    """Validate and normalize one extension provenance pin."""
    if not isinstance(data, Mapping):
        raise ExtensionDescriptorError("extension pin must be an object")
    required = {"id", "version", "implementation_hash", "source", "accepted_protocol_versions"}
    optional = {"descriptor_hash", "descriptor"}
    unknown = sorted(set(data) - required - optional)
    missing = sorted(required - set(data))
    if unknown:
        raise ExtensionDescriptorError(f"unknown extension pin key(s): {', '.join(unknown)}")
    if missing:
        raise ExtensionDescriptorError(f"missing extension pin key(s): {', '.join(missing)}")
    descriptor_id = data["id"]
    extension_version = data["version"]
    source = data["source"]
    if not isinstance(descriptor_id, str) or not descriptor_id:
        raise ExtensionDescriptorError("extension pin id must be a non-empty string")
    if not isinstance(extension_version, str) or not extension_version:
        raise ExtensionDescriptorError("extension pin version must be a non-empty string")
    _validate_provenance_source(source)
    implementation_hash = data["implementation_hash"]
    if not isinstance(implementation_hash, str):
        raise ExtensionDescriptorError("implementation_hash must be a lowercase SHA-256 hex string")
    _validate_implementation_hash(implementation_hash)
    descriptor_hash = data.get("descriptor_hash")
    if descriptor_hash is not None:
        if not isinstance(descriptor_hash, str):
            raise ExtensionDescriptorError("descriptor_hash must be a lowercase SHA-256 hex string")
        _validate_hash(descriptor_hash, "descriptor_hash")
    descriptor_payload = data.get("descriptor")
    descriptor = None
    if descriptor_payload is not None:
        if not isinstance(descriptor_payload, Mapping):
            raise ExtensionDescriptorError("descriptor must be an object")
        descriptor = parse_extension_descriptor(descriptor_payload)
    accepted_protocol_versions = _string_sequence(data["accepted_protocol_versions"], "accepted_protocol_versions")
    if not accepted_protocol_versions:
        raise ExtensionDescriptorError("accepted_protocol_versions must not be empty")
    return ExtensionPin(
        id=descriptor_id,
        version=extension_version,
        implementation_hash=implementation_hash,
        source=source,
        accepted_protocol_versions=accepted_protocol_versions,
        descriptor_hash=descriptor_hash,
        descriptor=descriptor,
    )


def validate_extension_pin(descriptor: ExtensionDescriptor, pin: ExtensionPin) -> None:
    """Ensure a provenance pin identifies and accepts the supplied descriptor."""
    if pin.id != descriptor.id or pin.version != descriptor.version:
        raise ExtensionDescriptorError("extension pin identity or version does not match descriptor")
    if descriptor.protocol not in pin.accepted_protocol_versions:
        raise ExtensionDescriptorError(f"extension pin does not accept descriptor protocol {descriptor.protocol!r}")
    if pin.descriptor_hash is not None and pin.descriptor_hash != _descriptor_hash(descriptor):
        raise ExtensionDescriptorError("extension pin descriptor hash does not match descriptor")
    if pin.descriptor is not None and pin.descriptor != descriptor:
        raise ExtensionDescriptorError("extension pin descriptor does not match descriptor")
    _validate_implementation_hash(pin.implementation_hash)


def _validate_implementation_hash(value: str) -> None:
    _validate_hash(value, "implementation_hash")


def _validate_hash(value: str, name: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ExtensionDescriptorError(f"{name} must be a lowercase SHA-256 hex string")


def _descriptor_hash(descriptor: ExtensionDescriptor) -> str:
    payload = json.dumps(descriptor.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_provenance_source(source: str | None) -> None:
    if source is not None and (not isinstance(source, str) or not source):
        raise ExtensionDescriptorError("source must be a non-empty string or null")
    if source is None:
        return
    parsed = urlsplit(source)
    if parsed.username is not None or parsed.password is not None:
        raise ExtensionDescriptorError("provenance source must not contain credentials")
    sensitive_names = {"token", "secret", "password", "passwd", "api_key", "apikey", "credential", "auth"}
    if any(any(name in key.lower() for name in sensitive_names) for key, _ in parse_qsl(parsed.query)):
        raise ExtensionDescriptorError("provenance source must not contain credentials")


def required_capabilities(mdl: MdlFile) -> tuple[str, ...]:
    """Return standard capabilities required by the normalized model."""
    required: set[str] = set()

    def visit(
        field_type: FieldType,
        field: FieldDef | ProjectionField | None = None,
        *,
        current_domain: str | None = None,
    ) -> None:
        if isinstance(field_type, EnumType):
            required.add("enums")
        elif isinstance(field_type, (EnumRefType, NamedType)):
            if isinstance(field_type, EnumRefType):
                required.add("enums")
            if current_domain is not None:
                try:
                    _, declaration = resolve_enum_type_ref(
                        mdl,
                        current_domain,
                        field_type.name,
                        exact_version=field_type.version if isinstance(field_type, EnumRefType) else None,
                    )
                except LookupError, TypeError:
                    pass
                else:
                    if isinstance(declaration, EnumProjectionDecl):
                        required.add("enum-projections")
        elif isinstance(field_type, MapType):
            required.add("maps")
            visit(field_type.key, field, current_domain=current_domain)
            visit(field_type.value, field, current_domain=current_domain)
        elif isinstance(field_type, ArrayType):
            visit(field_type.item, field, current_domain=current_domain)
        elif isinstance(field_type, ObjectType):
            required.add("records")
            for nested in field_type.fields:
                visit(nested.type, nested, current_domain=current_domain)
        elif isinstance(field_type, UnionType):
            required.add("unions")
            for variant in field_type.variants:
                visit(variant.type, field, current_domain=current_domain)
        if field is not None and field.constraints:
            required.add("constraints")

    for domain in mdl.domains:
        for model_versions in domain.models.values():
            for model_version in model_versions:
                required.add("records")
                if sum(field.is_key for field in model_version.fields) > 1:
                    required.add("composite-keys")
                for model_field in model_version.fields:
                    visit(model_field.type, model_field, current_domain=domain.name)
        for projection_versions in domain.projections.values():
            for projection_version in projection_versions:
                required.add("records")
                for projection_field in projection_version.fields:
                    field_type, _ = resolve_projection_field_type_and_optionality(
                        projection_field, projection_version, mdl
                    )
                    if field_type is not None:
                        visit(field_type, projection_field, current_domain=domain.name)
        for semantic_type in domain.semantic_types:
            required.add("semantic-types")
            visit(semantic_type.underlying, current_domain=domain.name)

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
