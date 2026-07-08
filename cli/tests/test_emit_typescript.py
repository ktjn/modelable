from __future__ import annotations

import hashlib

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.typescript import emit_typescript


def test_emit_typescript_model_and_projection(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"
  contact: "customer-team@example.com"
  description: "Customer identity and lifecycle."
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
    age?: int
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
    where c.name != ""
    group by c.name
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    refs = {artifact.ref for artifact in artifacts}
    assert "customer.Customer@1" in refs
    assert "customer.CustomerView@1" in refs

    model_art = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    assert model_art.content_hash == hashlib.sha256(model_art.content.encode("utf-8")).hexdigest()
    assert "export interface CustomerCustomerV1" in model_art.content
    assert "export type Customer = CustomerCustomerV1;" in model_art.content
    assert "/**" in model_art.content
    assert "@modelable domain: customer" in model_art.content
    assert "@modelable owner: customer-team" in model_art.content
    assert "@modelable contact: customer-team@example.com" in model_art.content
    assert "@modelable description: Customer identity and lifecycle." in model_art.content
    assert "@modelable kind: entity" in model_art.content
    assert "age?: number" in model_art.content

    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")
    assert proj_art.content_hash == hashlib.sha256(proj_art.content.encode("utf-8")).hexdigest()
    assert "export interface CustomerCustomerViewV1" in proj_art.content
    assert "export type CustomerView = CustomerCustomerViewV1;" in proj_art.content
    assert "@modelable source: customer.Customer@1" in proj_art.content
    assert '@modelable where: c.name != ""' in proj_art.content
    assert "@modelable groupBy: c.name" in proj_art.content


def test_emit_typescript_projection_uses_source_version_types(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  entity Customer @ 2 (additive) {
    @key customerId: uuid
    name: int
    email: string
  }

  projection CustomerView @ 2
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@2")
    assert "customerId: string" in proj_art.content
    assert "name: string" in proj_art.content


def test_emit_typescript_projection_with_source_version_range_uses_matching_source_types(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  entity Customer @ 2 (additive) {
    @key customerId: uuid
    name: int
    email: string
  }

  projection CustomerView @ 1
    from customer.Customer @ >=1<3 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")
    assert "@modelable source: customer.Customer@>=1<3" in proj_art.content
    assert "customerId: string" in proj_art.content
    assert "name: number" in proj_art.content


def test_emit_typescript_warns_on_computed_projection_field(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    displayName = c.name + "!"
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")
    assert proj_art.warnings
    assert any("EMIT002" in warning for warning in proj_art.warnings)


def test_emit_typescript_warns_on_named_type_field(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: Address
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    model_art = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    assert model_art.warnings
    assert any("EMIT003" in warning for warning in model_art.warnings)


def test_emit_typescript_decimal_maps_to_string(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain finance {
  owner: "test-team"
  entity Invoice @ 1 (additive) {
    @key invoiceId: uuid
    amount: decimal(12, 2)
    taxRate?: decimal(5, 4)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "finance.Invoice@1")
    assert "amount: string;" in art.content
    assert "taxRate?: string;" in art.content


def test_emit_typescript_fixed_width_integers_map_to_number_or_bigint(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain types {
  owner: "test-team"
  entity Widths @ 1 (additive) {
    @key id: uuid
    a: u8
    b: u16
    c: u32
    d: u64
    e: u128
    f: i8
    g: i16
    h: i32
    i: i64
    j: i128
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "types.Widths@1")
    assert "a: number;" in art.content
    assert "b: number;" in art.content
    assert "c: number;" in art.content
    assert "d: bigint;" in art.content
    assert "e: bigint;" in art.content
    assert "f: number;" in art.content
    assert "g: number;" in art.content
    assert "h: number;" in art.content
    assert "i: bigint;" in art.content
    assert "j: bigint;" in art.content


def test_emit_typescript_temporal_types_map_to_string(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain events {
  owner: "test-team"
  entity Event @ 1 (additive) {
    @key eventId: uuid
    occurredAt: timestamp
    scheduledDate: date
    windowStart: time
    ttl: duration
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "events.Event@1")
    assert "occurredAt: string;" in art.content
    assert "scheduledDate: string;" in art.content
    assert "windowStart: string;" in art.content
    assert "ttl: string;" in art.content


def test_emit_typescript_uses_stable_interface_names(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    model_art = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    proj_art = next(artifact for artifact in artifacts if artifact.ref == "customer.CustomerView@1")

    assert "export interface CustomerCustomerV1" in model_art.content
    assert "export interface CustomerCustomerViewV1" in proj_art.content


def test_cli_compile_typescript_writes_files(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    out = tmp_path / "dist" / "types"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "typescript", "--out", str(out)],
        )

    assert result.exit_code == 0
    assert (out / "customer.Customer.v1.ts").exists()
    assert any(
        len(part) == 64 and all(ch in "0123456789abcdef" for ch in part.lower()) for part in result.output.split()
    )
    text = (out / "customer.Customer.v1.ts").read_text(encoding="utf-8")
    assert "export interface CustomerCustomerV1" in text
    assert "export type Customer = CustomerCustomerV1;" in text


def test_emit_typescript_wire_json_string_int_maps_to_string(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    @wire(json: "string", rust.type: "u64")
    startTimeUnixNano: int
    name: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    # ADR-030 u64-as-string: json wire hint overrides int → string in TypeScript
    assert "startTimeUnixNano: string;" in art.content
    # plain string field unaffected
    assert "name: string;" in art.content


def test_emit_typescript_wire_json_string_float_maps_to_string(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain finance {
  owner: "test-team"
  entity Price @ 1 (additive) {
    @key priceId: uuid
    @wire(json: "string")
    value: float
    label: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "finance.Price@1")
    assert "value: string;" in art.content
    assert "label: string;" in art.content


def test_emit_typescript_wire_enum_screaming_snake_case(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    @wire(json.case: "SCREAMING_SNAKE_CASE")
    spanKind: enum(Internal, Server, Client, Producer, Consumer)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    assert "'INTERNAL'" in art.content
    assert "'SERVER'" in art.content
    assert "'CLIENT'" in art.content
    # IDL names should NOT appear as enum values
    assert "'Internal'" not in art.content
    assert "'Server'" not in art.content


def test_emit_typescript_wire_enum_case_camel(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain events {
  owner: "test-team"
  entity Event @ 1 (additive) {
    @key eventId: uuid
    @wire(json.case: "camelCase")
    eventType: enum(PageView, ButtonClick, FormSubmit)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "events.Event@1")
    assert "'pageView'" in art.content
    assert "'buttonClick'" in art.content
    assert "'formSubmit'" in art.content


def test_emit_typescript_json_primitive_maps_to_unknown(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain example {
  owner: "test-team"
  entity Widget @ 1 (additive) {
    @key id: uuid
    payload: json
    attributes: map<string, json>
    tags: array<json>
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    model_art = next(a for a in artifacts if a.ref == "example.Widget@1")

    assert "payload: unknown;" in model_art.content
    assert "attributes: Record<string, unknown>;" in model_art.content
    assert "tags: unknown[];" in model_art.content


def test_emit_typescript_wire_enum_overrides(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    @wire(json.overrides: { Internal: "INTERNAL", Server: "SERVER" })
    spanKind: enum(Internal, Server, Client)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    # overridden values use the wire representation
    assert "'INTERNAL'" in art.content
    assert "'SERVER'" in art.content
    # non-overridden value stays as-is
    assert "'Client'" in art.content


def test_emit_typescript_wire_enum_case_without_wire_hint_unchanged(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    spanKind: enum(Internal, Server, Client)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    # No wire hint — values are emitted verbatim from the IDL
    assert "'Internal'" in art.content
    assert "'Server'" in art.content
    assert "'Client'" in art.content


def test_emit_typescript_model_level_field_case_snake_case(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"

  @wire(json.fieldCase: "snake_case")
  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
    startTimeUnixNano: int
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    assert "span_id: string;" in art.content
    assert "trace_id: string;" in art.content
    assert "start_time_unix_nano: number;" in art.content
    assert "spanId" not in art.content
    assert "traceId" not in art.content


def test_emit_typescript_projection_level_field_case_independent_of_model(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"

  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
  }

  @wire(json.fieldCase: "snake_case")
  projection SpanRow @ 1
    from tracing.Span @ 1 as s
  {
    spanId <- s.spanId
    traceId <- s.traceId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")

    model_art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    assert "spanId: string;" in model_art.content
    assert "traceId: string;" in model_art.content

    proj_art = next(a for a in artifacts if a.ref == "tracing.SpanRow@1")
    assert "span_id: string;" in proj_art.content
    assert "trace_id: string;" in proj_art.content


def test_emit_typescript_model_without_field_case_is_unchanged(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    assert "spanId: string;" in art.content
    assert "traceId: string;" in art.content


def test_emit_typescript_tracing_span_field_case_end_to_end(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "platform-team"

  @wire(json.fieldCase: "snake_case")
  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
    parentSpanId?: string
    tenantId: uuid
    @wire(json.case: "SCREAMING_SNAKE_CASE")
    spanKind: enum(Internal, Server, Client, Producer, Consumer)
    @wire(rust.type: "u64")
    startTimeUnixNano: int
    attributes: map<string, json>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")

    expected_fields = [
        "span_id: string;",
        "trace_id: string;",
        "parent_span_id?: string;",
        "tenant_id: string;",
        "start_time_unix_nano: number;",
        "attributes: Record<string, unknown>;",
    ]
    for expected in expected_fields:
        assert expected in art.content, art.content

    assert "'INTERNAL' | 'SERVER' | 'CLIENT' | 'PRODUCER' | 'CONSUMER'" in art.content
    assert "span_kind:" in art.content


def test_emit_typescript_ref_field_emits_type_reference_and_import(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain address {
  owner: "address-team"
  entity Address @ 1 (additive) {
    @key addressId: uuid
    line1: string
  }
}

domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: ref<address.Address>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    customer_art = next(a for a in artifacts if a.ref == "customer.Customer@1")
    # ref<address.Address> resolved in workspace → emit stable interface name, not "string"
    assert "address: AddressAddressV1;" in customer_art.content
    # An import statement must be emitted at the top of the file
    assert "import type { AddressAddressV1 }" in customer_art.content


def test_emit_typescript_ref_field_unresolvable_falls_back_to_string(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: ref<external.Address>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    customer_art = next(a for a in artifacts if a.ref == "customer.Customer@1")
    # ref to model not in workspace falls back to "string"
    assert "address: string;" in customer_art.content


def test_emit_typescript_array_of_enum_produces_valid_type(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain catalog {
  owner: "test-team"
  entity Product @ 1 (additive) {
    @key productId: uuid
    tags: array<enum(New, Sale, Featured)>
    primaryTag: enum(New, Sale, Featured)
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "catalog.Product@1")
    # array<enum(...)> must emit a parenthesised union array: ('A' | 'B' | 'C')[]
    assert "('New' | 'Sale' | 'Featured')[]" in art.content
    # scalar enum field is unchanged
    assert "'New' | 'Sale' | 'Featured'" in art.content


def test_emit_typescript_named_type_in_same_workspace_generates_import(tmp_path):
    """NamedType field whose type exists in the workspace gets an import (issue #118)."""
    (tmp_path / "test.mdl").write_text(
        """
domain nlq {
  owner: "test-team"
  value NlqTimeRange {
    from: string
    to: string
  }
  value NlqIr {
    timeRange: NlqTimeRange
    query: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    ir_art = next(a for a in artifacts if "NlqIr" in a.ref)

    # Resolved named type uses the exported short alias as the canonical name.
    assert "timeRange: NlqTimeRange;" in ir_art.content
    assert 'import type { NlqTimeRange } from "./nlq.NlqTimeRange.v0";' in ir_art.content
    assert "NlqNlqTimeRangeV" not in ir_art.content
    # EMIT003 must NOT be emitted when the type is successfully resolved
    assert not any("EMIT003" in w for w in ir_art.warnings)


def test_emit_typescript_named_type_imports_after_docblock_and_uses_alias(tmp_path):
    """NamedType imports use the exported short alias after the metadata docblock."""
    (tmp_path / "test.mdl").write_text(
        """
domain nlq {
  owner: "test-team"
  value NlqFilter {
    field: string
    value: string
  }
  value NlqIr {
    filters: array<NlqFilter>
    query: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    ir_art = next(a for a in artifacts if "NlqIr" in a.ref)
    lines = ir_art.content.splitlines()

    docblock_end = lines.index(" */")
    import_index = lines.index('import type { NlqFilter } from "./nlq.NlqFilter.v0";')
    interface_index = lines.index("export interface NlqNlqIrV0 {")

    assert docblock_end < import_index < interface_index
    assert "filters: NlqFilter[];" in ir_art.content
    assert "NlqNlqFilterV" not in ir_art.content


def test_emit_typescript_named_type_unresolvable_still_warns(tmp_path):
    """NamedType not found in workspace still emits EMIT003 (issue #118)."""
    (tmp_path / "test.mdl").write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: ExternalAddress
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "customer.Customer@1")
    assert any("EMIT003" in w for w in art.warnings)
    # Falls back to emitting the bare name
    assert "ExternalAddress" in art.content
