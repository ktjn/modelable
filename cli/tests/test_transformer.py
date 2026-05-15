from modelable.parser.ir import (
    AnnKey,
    ChangeKind,
    DomainDef,
    FieldDef,
    MdlFile,
    ModelKind,
    ModelVersion,
    PrimitiveType,
)
from modelable.parser.parse import parse_text_to_ir


def test_ir_model_construction():
    field = FieldDef(
        name="customerId",
        type=PrimitiveType(kind="uuid"),
        optional=False,
        annotations=[AnnKey()],
    )
    version = ModelVersion(
        model_kind=ModelKind.entity,
        version=2,
        change_kind=ChangeKind.additive,
        fields=[field],
    )
    domain = DomainDef(
        name="customer",
        models={"Customer": [version]},
    )
    mdl = MdlFile(domains=[domain])

    assert mdl.domains[0].name == "customer"
    assert mdl.domains[0].models["Customer"][0].version == 2
    assert mdl.domains[0].models["Customer"][0].fields[0].is_key


def test_parser_package_exports_ir_models():
    from modelable.parser import MdlFile as ExportedMdlFile

    assert ExportedMdlFile is MdlFile


def test_transform_simple_model():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "customer-platform"
      entity Customer @ 2 (additive) {
        @key
        customerId: uuid
        @pii
        email?: string
        status: enum(active, blocked)
      }
    }
    """)

    assert len(mdl.domains) == 1
    domain = mdl.domains[0]
    assert domain.name == "customer"
    assert domain.owner == "customer-platform"
    versions = domain.models["Customer"]
    assert len(versions) == 1
    version = versions[0]
    assert version.version == 2
    assert version.change_kind.value == "additive"
    assert version.model_kind.value == "entity"
    fields = {field.name: field for field in version.fields}
    assert fields["customerId"].is_key
    assert fields["customerId"].type.kind == "uuid"
    assert fields["email"].is_pii
    assert fields["email"].optional
    assert fields["status"].type.kind == "enum"
    assert fields["status"].type.values == ["active", "blocked"]


def test_transform_projection():
    mdl = parse_text_to_ir("""
    domain billing {
      projection BillingCustomer @ 1
        from customer.Customer @ 2 as c
      {
        billingCustomerId <- c.customerId
        isBillable = c.status == "active"
      }
    }
    """)

    domain = mdl.domains[0]
    versions = domain.projections["BillingCustomer"]
    assert len(versions) == 1
    projection = versions[0]
    assert projection.version == 1
    assert projection.source.model == "customer.Customer"
    assert projection.source.alias == "c"
    assert projection.source.version.kind == "exact"
    assert projection.source.version.version == 2
    fields = {field.name: field for field in projection.fields}
    assert fields["billingCustomerId"].mapping.kind == "direct"
    assert fields["billingCustomerId"].mapping.source_alias == "c"
    assert fields["billingCustomerId"].mapping.source_field == "customerId"
    assert fields["isBillable"].mapping.kind == "computed"
    assert "c.status" in fields["isBillable"].mapping.expression


def test_transform_version_range():
    mdl = parse_text_to_ir("""
    domain billing {
      projection Ranged @ 1
        from customer.Customer @ >=2 <4 as c
      {
        id <- c.customerId
      }
    }
    """)

    projection = mdl.domains[0].projections["Ranged"][0]
    assert projection.source.version.kind == "range"
    assert projection.source.version.min_inclusive == 2
    assert projection.source.version.max_exclusive == 4


def test_transform_fixture_files(fixture_path):
    from modelable.parser.parse import parse_file_to_ir

    customer_mdl = parse_file_to_ir(fixture_path / "customer.mdl")
    assert customer_mdl.domains[0].name == "customer"
    billing_mdl = parse_file_to_ir(fixture_path / "billing_projection.mdl")
    assert "BillingCustomer" in billing_mdl.domains[0].projections
