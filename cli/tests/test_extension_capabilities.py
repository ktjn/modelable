from __future__ import annotations

import pytest

from modelable.emitters.targets import get_codegen_target
from modelable.extensions import (
    PROTOCOL,
    ExtensionDescriptor,
    ExtensionDescriptorError,
    required_capabilities,
    validate_extension_admission,
    validate_extension_capabilities,
)
from modelable.parser.parse import parse_text_to_ir
from modelable.planner.protocol import PLAN_SCHEMA


def _descriptor(*capabilities: str) -> ExtensionDescriptor:
    return ExtensionDescriptor(
        protocol=PROTOCOL,
        id="test.target",
        version="test",
        accepted_plan_versions=("modelable.plan/v0",),
        capabilities=tuple(capabilities),
        configuration_schema=None,
        output_kinds=("artifact",),
        compatibility_support=False,
    )


def test_required_capabilities_are_canonical_and_derived_from_field_types() -> None:
    mdl = parse_text_to_ir(
        """
        domain orders {
          entity Order @ 1 (additive) {
            @key id: uuid
            labels: map<string, string>
            method: union<kind> { card: Card, bank: Bank }
          }
        }
        """
    )

    assert required_capabilities(mdl) == ("maps", "records", "unions")


def test_composite_keys_require_explicit_target_capability() -> None:
    mdl = parse_text_to_ir(
        """
        domain orders {
          entity OrderLine @ 1 (additive) {
            @key orderId: uuid
            @key lineNumber: int
          }
        }
        """
    )

    assert required_capabilities(mdl) == ("composite-keys", "records")
    validate_extension_capabilities(_descriptor("composite-keys", "records"), mdl)
    with pytest.raises(ExtensionDescriptorError, match="composite-keys"):
        validate_extension_capabilities(_descriptor("records"), mdl)


def test_enum_projection_fields_require_the_target_capability() -> None:
    mdl = parse_text_to_ir(
        """
        domain orders {
          semantic OrderStatus @ 1 (additive): enum(active, blocked)
          enum projection PublicStatus @ 1 (additive) from OrderStatus @ 1 pick(active)
          entity Order @ 1 (additive) {
            @key id: uuid
            status: PublicStatus
          }
        }
        """
    )

    assert required_capabilities(mdl) == ("enum-projections", "enums", "records", "semantic-types")
    validate_extension_capabilities(_descriptor("enum-projections", "enums", "records", "semantic-types"), mdl)
    with pytest.raises(ExtensionDescriptorError, match="enum-projections"):
        validate_extension_capabilities(_descriptor("enums", "records"), mdl)


def test_capability_validation_rejects_unsupported_requirements_deterministically() -> None:
    mdl = parse_text_to_ir(
        """
        domain orders {
          entity Order @ 1 (additive) {
            @key id: uuid
            method: union<kind> { card: Card, bank: Bank }
          }
        }
        """
    )

    with pytest.raises(
        ExtensionDescriptorError,
        match=r"target 'test\.target' does not support required capability 'unions'",
    ):
        validate_extension_capabilities(_descriptor("records"), mdl)


def test_capability_validation_accepts_all_required_capabilities() -> None:
    mdl = parse_text_to_ir(
        """
        domain orders {
          entity Order @ 1 (additive) {
            @key id: uuid
            labels: map<string, string>
          }
        }
        """
    )

    validate_extension_capabilities(_descriptor("maps", "records"), mdl)


def test_builtin_targets_advertise_capabilities_they_implement() -> None:
    assert "unions" in get_codegen_target("json-schema").extension_descriptor().capabilities
    assert "unions" in get_codegen_target("openapi").extension_descriptor().capabilities
    assert "unions" not in get_codegen_target("rust").extension_descriptor().capabilities
    assert "enum-projections" in get_codegen_target("rust").extension_descriptor().capabilities
    assert "enum-projections" not in get_codegen_target("markdown").extension_descriptor().capabilities


def test_structured_targets_advertise_composite_key_capability() -> None:
    for target in ("json-schema", "openapi", "protobuf", "grpc", "sql-postgres", "sql-clickhouse"):
        assert "composite-keys" in get_codegen_target(target).extension_descriptor().capabilities
    assert "composite-keys" not in get_codegen_target("python").extension_descriptor().capabilities


def test_codegen_admission_rejects_composite_keys_for_unsupported_targets() -> None:
    mdl = parse_text_to_ir(
        """
        domain orders {
          entity OrderLine @ 1 (additive) {
            @key orderId: uuid
            @key lineNumber: int
          }
        }
        """
    )

    validate_extension_admission(
        get_codegen_target("sql-postgres").extension_descriptor(),
        mdl,
        plan_version=PLAN_SCHEMA,
    )
    with pytest.raises(ExtensionDescriptorError, match="composite-keys"):
        validate_extension_admission(
            get_codegen_target("python").extension_descriptor(),
            mdl,
            plan_version=PLAN_SCHEMA,
        )


def test_extension_admission_rejects_targets_without_compatibility_support() -> None:
    mdl = parse_text_to_ir(
        """
        domain orders {
          entity Order @ 1 (additive) { @key id: uuid }
        }
        """
    )

    with pytest.raises(ExtensionDescriptorError, match="does not support compatibility analysis"):
        validate_extension_admission(
            _descriptor("records"),
            mdl,
            plan_version=PLAN_SCHEMA,
            require_compatibility_support=True,
        )
