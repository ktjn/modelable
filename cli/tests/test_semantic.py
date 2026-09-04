from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace, load_workspace_from_sources
from modelable.parser.parse import parse_text_to_ir
from modelable.validation.semantic import validate


def test_valid_entity_passes():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_composite_key_is_validated_as_an_ordered_key_set():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity OrderLineItem @ 1 (additive) {
        @key orderId: uuid
        @key lineItemId: uuid
        sku: string
        quantity: int
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_composite_primary_index_must_preserve_key_order():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity OrderLineItem @ 1 (additive) {
        @key orderId: uuid
        @key lineItemId: uuid
      }
      index OrderLineItem @ 1 {
        primary lineItemId, orderId
      }
    }
    """)

    errors = validate(mdl)

    assert any("primary index order" in error for error in errors)


def test_entity_missing_key_fails():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        customerId: uuid
        name: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("key" in error.lower() for error in errors)


def test_event_must_not_have_key():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      event OrderPlaced @ 1 (additive) {
        @key orderId: uuid
        amount: decimal(10, 2)
      }
    }
    """)

    errors = validate(mdl)

    assert any("key" in error.lower() for error in errors)


def test_versions_must_be_ascending():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 2 (additive) {
        @key customerId: uuid
      }
      entity Customer @ 1 (additive) {
        @key customerId: uuid
      }
    }
    """)

    errors = validate(mdl)

    assert any("version" in error.lower() for error in errors)


def test_additive_version_rejects_breaking_changes():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
      entity Customer @ 2 (additive) {
        @key customerId: uuid
      }
    }
    """)

    errors = validate(mdl)

    assert any("additive declaration includes incompatible changes" in error for error in errors)


def test_additive_version_rejects_optional_to_required_change():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        email?: string
      }
      entity Customer @ 2 (additive) {
        @key customerId: uuid
        email: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("presence change email" in error for error in errors)


def test_additive_version_allows_optional_additions():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
      entity Customer @ 2 (additive) {
        @key customerId: uuid
        name: string
        email?: string
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_additive_version_allows_new_access_block():
    mdl = parse_text_to_ir("""
    domain patient {
      owner: "test-team"
      entity Patient @ 1 (additive) {
        @key patientId: uuid
        name: string
      }
      entity Patient @ 2 (additive) {
        @key patientId: uuid
        name: string
        access {
          entity care-team [read]
        }
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_breaking_version_requires_incompatible_change():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
      entity Customer @ 2 (breaking) {
        @key customerId: uuid
        name: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("breaking declaration must include at least one incompatible change" in error for error in errors)


def test_aggregate_function_without_group_by_fails():
    mdl = parse_text_to_ir("""
    domain stats {
      owner: "test-team"
      projection BadStats @ 1
        from orders.Order @ 1 as o
      {
        total = sum(o.amount)
      }
    }
    """)

    errors = validate(mdl)

    assert any("group by" in error.lower() or "aggregat" in error.lower() for error in errors)


def test_valid_classification_levels_pass():
    for level in ("open", "internal", "confidential", "restricted", "secret"):
        mdl = parse_text_to_ir(f"""
        domain payments {{
          owner: "test-team"
          entity Payment @ 1 (additive) {{
            @key paymentId: uuid
            @classification("{level}") cardNumber: string
          }}
        }}
        """)
        errors = validate(mdl)
        assert errors == [], f"Expected no errors for level '{level}', got: {errors}"


def test_invalid_classification_level_fails():
    mdl = parse_text_to_ir("""
    domain payments {
      owner: "test-team"
      entity Payment @ 1 (additive) {
        @key paymentId: uuid
        @classification("top-secret") cardNumber: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("classification" in error.lower() for error in errors)
    assert any("top-secret" in error for error in errors)


def test_invalid_classification_level_on_projection_field_fails():
    mdl = parse_text_to_ir("""
    domain payments {
      owner: "test-team"
      projection PaymentSummary @ 1
        from payments.Payment @ 1 as p
      {
        @classification("classified") cardNumber <- p.cardNumber
      }
    }
    """)

    errors = validate(mdl)

    assert any("classification" in error.lower() for error in errors)
    assert any("classified" in error for error in errors)


def test_aggregate_function_with_group_by_passes():
    mdl = parse_text_to_ir("""
    domain stats {
      owner: "test-team"
      projection GoodStats @ 1
        from orders.Order @ 1 as o
        group by o.customerId
      {
        customerId <- o.customerId
        total = sum(o.amount)
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_unknown_wire_target_fails():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(unknown: "string")
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("unknown wire target" in error.lower() for error in errors)


def test_json_wire_requires_string_encoding():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(json: "uuid")
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("unsupported json wire encoding" in error.lower() for error in errors)


def test_json_wire_rejects_non_integer_string_fields():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(json: "string")
        name: string
      }
    }
    """)

    errors = validate(mdl)

    assert any("only supports @wire(json: ...)" in error for error in errors)


def test_json_wire_case_on_enum_requires_no_encoding():
    """@wire(json.case: "SCREAMING_SNAKE_CASE") on an enum field is valid without json: encoding."""
    mdl = parse_text_to_ir("""
    domain events {
      owner: "test-team"
      entity Event @ 1 (additive) {
        @key eventId: uuid
        @wire(json.case: "SCREAMING_SNAKE_CASE")
        status: enum(Active, Inactive)
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_json_wire_case_on_non_enum_is_rejected():
    """@wire(json.case: ...) on a non-enum field should be rejected."""
    mdl = parse_text_to_ir("""
    domain events {
      owner: "test-team"
      entity Event @ 1 (additive) {
        @key eventId: uuid
        @wire(json: "string", json.case: "SCREAMING_SNAKE_CASE")
        amount: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("non-enum" in error.lower() for error in errors)


def test_json_wire_overrides_on_enum_requires_no_encoding():
    """@wire(json.overrides: {...}) on an enum field is valid without json: encoding."""
    mdl = parse_text_to_ir("""
    domain events {
      owner: "test-team"
      entity Event @ 1 (additive) {
        @key eventId: uuid
        @wire(json.overrides: { Active: "active", Inactive: "inactive" })
        status: enum(Active, Inactive)
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_inline_object_wire_hints_are_validated_recursively():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        payload: object {
          @wire(json: "bad_encoding")
          count: int
        }
      }
    }
    """)

    errors = validate(mdl)

    assert any("payload" in error.lower() and "unsupported json wire encoding" in error.lower() for error in errors)


def test_rust_type_override_is_allowed_on_temporal_fields():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(rust.type: "i64")
        startedAt: timestamp
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_projection_field_wire_hints_validate_against_source_type():
    mdl = parse_text_to_ir("""
    domain metrics {
      owner: "test-team"
      entity Span @ 1 (additive) {
        @key spanId: string
        amount: int
      }

      projection SpanView @ 1
        from metrics.Span @ 1 as s
      {
        @wire(json: "string")
        amount <- s.spanId
      }
    }
    """)

    errors = validate(mdl)

    assert any("only supports @wire(json: ...)" in error for error in errors)


def test_model_level_json_field_case_snake_case_passes():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(json.fieldCase: "snake_case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_model_level_json_field_case_invalid_value_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(json.fieldCase: "kebab-case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("unsupported json.fieldcase" in error.lower() for error in errors)


def test_field_level_json_field_case_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(json.fieldCase: "snake_case")
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("json.fieldcase" in error.lower() for error in errors)


def test_projection_level_json_field_case_snake_case_passes():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }

      @wire(json.fieldCase: "snake_case")
      projection SpanRow @ 1
        from tracing.Span @ 1 as s
      {
        spanId <- s.spanId
        startTimeUnixNano <- s.startTimeUnixNano
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_model_level_wire_target_other_than_json_field_case_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(rust.case: "snake_case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("only @wire(json.fieldcase: ...)" in error.lower() for error in errors)


def test_fixed_width_default_out_of_range_is_error():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        score: u8 = 300
      }
    }
    """)

    errors = validate(mdl)

    assert any("u8" in e and "range" in e.lower() for e in errors)


def test_fixed_width_default_in_range_is_valid():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        score: u8 = 200
        delta: i8 = -100
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_fixed_width_negative_default_on_unsigned_is_error():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        score: u32 = -1
      }
    }
    """)

    errors = validate(mdl)

    assert any("u32" in e for e in errors)


def test_fixed_binary_length_out_of_range_is_error():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        keyHash: binary(5000)
      }
    }
    """)

    errors = validate(mdl)

    assert any("keyHash" in e and "4096" in e for e in errors)


def test_fixed_binary_zero_length_is_error():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        keyHash: binary(0)
      }
    }
    """)

    errors = validate(mdl)

    assert any("keyHash" in e for e in errors)


def test_fixed_binary_in_range_is_valid():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        keyHash: binary(32)
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_semantic_type_rejects_array_underlying():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Bad : array<string>
    }
    """)
    errors = validate(mdl)
    assert any("Bad" in e for e in errors)


def test_semantic_type_chained_underlying_is_valid():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Base : u32
      semantic Wrapped : Base
    }
    """)
    assert validate(mdl) == []


def test_semantic_type_dangling_underlying_reference_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Wrapped : DoesNotExist
    }
    """)
    errors = validate(mdl)
    assert any("Wrapped" in e and "DoesNotExist" in e for e in errors)


def test_semantic_type_cycle_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic A : B
      semantic B : A
    }
    """)
    errors = validate(mdl)
    assert any("cycle" in e.lower() for e in errors)


def test_semantic_type_chain_resolves_qualified_cross_domain_reference():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      semantic Id: uuid
    }
    domain billing {
      owner: "test-team"
      semantic InvoiceId: orders.Id
    }
    """)

    assert validate(mdl) == []


def test_semantic_type_chain_rejects_ambiguous_bare_reference():
    mdl = parse_text_to_ir("""
    domain alpha {
      owner: "test-team"
      semantic SharedId: uuid
    }
    domain beta {
      owner: "test-team"
      semantic SharedId: string
    }
    domain consumer {
      owner: "test-team"
      semantic Wrapped: SharedId
    }
    """)

    errors = validate(mdl)
    assert any("ambiguous" in e.lower() and "SharedId" in e for e in errors)


def test_semantic_type_cycle_across_domains_is_error():
    mdl = parse_text_to_ir("""
    domain alpha {
      owner: "test-team"
      semantic A: beta.B
    }
    domain beta {
      owner: "test-team"
      semantic B: alpha.A
    }
    """)

    errors = validate(mdl)
    assert any("cycle" in e.lower() for e in errors)


def test_semantic_type_duplicate_name_in_domain_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic ModuleId : u32
      semantic ModuleId : u64
    }
    """)
    errors = validate(mdl)
    assert any("ModuleId" in e for e in errors)


def test_semantic_type_name_colliding_with_model_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Schema : u32
      entity Schema @ 1 (additive) {
        @key id: uuid
      }
    }
    """)
    errors = validate(mdl)
    assert any("Schema" in e for e in errors)


def test_semantic_type_name_colliding_with_projection_is_error():
    """Evolution plan E11: a projection sharing a name with a semantic type
    is a rename/reference-resolution hazard the same way a model collision
    is -- both live in the same qualified `domain.Name@version` namespace,
    and the token-based language services can't disambiguate a qualified
    reference between them by syntax alone."""
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      semantic Status : u32
      entity Widget @ 1 (additive) {
        @key id: uuid
      }
      projection Status @ 1
        from platform.Widget @ 1 as w
      {
        id <- w.id
      }
    }
    """)
    errors = validate(mdl)
    assert any("Status" in e and "projection" in e for e in errors)


def test_ref_type_requires_identity_bearing_model(tmp_path):
    source = tmp_path / "model.mdl"
    source.write_text(
        """
    domain foundation {
      owner: "test-team"
      value Address @ 1 (additive) {
        street: string
      }
    }
    domain billing {
      owner: "test-team"
      entity Invoice @ 1 (additive) {
        @key invoiceId: uuid
        address: ref<foundation.Address @ 1>
      }
    }
    """
    )
    workspace = load_workspace(source)
    assert any(
        "ref<foundation.Address" in error.message and "identity" in error.message.lower() for error in workspace.errors
    )


def test_index_decl_primary_must_match_key_field():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
             status:  string
      }
      index Order @ 1 {
        primary status
      }
    }
    """)
    errors = validate(mdl)
    assert any("Order" in e and "primary" in e.lower() for e in errors)


def test_index_decl_valid_primary_and_secondary_is_valid():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
             status:  string
      }
      index Order @ 1 {
        primary orderId
        secondary byStatus {
          key: [status]
        }
      }
    }
    """)
    assert validate(mdl) == []


def test_index_decl_secondary_field_reference_must_exist():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
      }
      index Order @ 1 {
        primary orderId
        secondary byMissing {
          key: [doesNotExist]
        }
      }
    }
    """)
    errors = validate(mdl)
    assert any("doesNotExist" in e for e in errors)


def test_index_decl_duplicate_secondary_name_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
             status:  string
      }
      index Order @ 1 {
        primary orderId
        secondary byStatus {
          key: [status]
        }
        secondary byStatus {
          key: [status]
        }
      }
    }
    """)
    errors = validate(mdl)
    assert any("byStatus" in e for e in errors)


def test_index_decl_referencing_unknown_model_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      index DoesNotExist @ 1 {
        primary id
      }
    }
    """)
    errors = validate(mdl)
    assert any("DoesNotExist" in e for e in errors)


def test_index_decl_on_value_model_is_error():
    mdl = parse_text_to_ir("""
    domain platform {
      owner: "test-team"
      value Money @ 1 (additive) {
        amount: decimal(10, 2)
      }
      index Money @ 1 {
        primary amount
      }
    }
    """)
    errors = validate(mdl)
    assert any("Money" in e for e in errors)


def test_unresolvable_ref_target_is_a_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.MissingEntity>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert any("customerRef" in e.message and "ref<" in e.message for e in workspace.errors)


def test_unresolvable_ref_version_is_a_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<orders.Customer @ 99>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert any("customerRef" in e.message for e in workspace.errors)


def test_resolvable_ref_produces_no_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<orders.Customer @ 1>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert workspace.errors == []


def test_ref_across_source_files_resolves_correctly():
    """The scenario that broke an earlier version of this plan: a ref<> in
    one file pointing at a model declared in a sibling file. This must
    resolve cleanly — it is the normal pattern in samples/scenarios/."""
    customer_source = WorkspaceDocumentSource(
        path=Path("customer.mdl"),
        uri="file:///customer.mdl",
        text="""
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
        }
        """,
    )
    orders_source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.Customer @ 1>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([customer_source, orders_source])

    assert workspace.errors == []


def test_unversioned_ref_produces_a_non_blocking_warning_naming_resolved_version():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            name?: string
          }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<orders.Customer>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert workspace.errors == []
    ref_warnings = [w for w in workspace.warnings if w.code == "REF"]
    assert len(ref_warnings) == 1
    assert "customerRef" in ref_warnings[0].message
    assert "version 2" in ref_warnings[0].message


def test_ref_nested_in_array_is_validated():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            items: array<ref<catalog.MissingItem>>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert any("items" in e.message for e in workspace.errors)


def test_duplicate_enum_member_is_a_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            state: enum(active, blocked, active)
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    errors = [e.message for e in workspace.errors]
    assert any("state" in message and "duplicate enum member 'active'" in message for message in errors), errors


def test_duplicate_enum_members_nested_in_containers_are_sem_errors():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            tags: array<enum(red, blue, red)>
            attrs: map<string, enum(on, off, on)>
            details: object {
              level: enum(low, high, low)
            }
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    errors = [e.message for e in workspace.errors]
    assert any("tags[]" in message and "duplicate enum member 'red'" in message for message in errors), errors
    assert any("attrs{}" in message and "duplicate enum member 'on'" in message for message in errors), errors
    assert any("details.level" in message and "duplicate enum member 'low'" in message for message in errors), errors


def test_valid_nested_enums_produce_no_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            state: enum(active, blocked)
            tags: array<enum(red, blue)>
            attrs: map<string, enum(on, off)>
            details: object {
              level: enum(low, high)
            }
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert not [e.message for e in workspace.errors if "enum" in e.message]


def test_json_case_mapping_two_members_to_one_wire_value_is_a_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            @wire(json.case: "snake_case")
            state: enum(fooBar, foo_bar)
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    errors = [e.message for e in workspace.errors]
    assert any(
        "state" in message and "same json wire value 'foo_bar'" in message and "'fooBar'" in message
        for message in errors
    ), errors


def test_json_overrides_mapping_two_members_to_one_wire_value_is_a_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            @wire(json.overrides: { active: "on", resumed: "on" })
            state: enum(active, resumed, blocked)
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    errors = [e.message for e in workspace.errors]
    assert any("state" in message and "same json wire value 'on'" in message for message in errors), errors


def test_distinct_json_wire_values_produce_no_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            @wire(json.case: "snake_case")
            state: enum(active, blocked)
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert not [e.message for e in workspace.errors if "wire value" in e.message]
