from modelable.parser.ir import (
    AnnKey,
    ChangeKind,
    ClassificationLevel,
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
      contact: "customer@example.com"
      entity Customer @ 2 (additive) {
        @key
        customerId: uuid
        @pii
        email?: string
        status: enum(active, blocked)
        marketingConsent: bool = false
      }
    }
    """)

    assert len(mdl.domains) == 1
    domain = mdl.domains[0]
    assert domain.name == "customer"
    assert domain.owner == "customer-platform"
    assert domain.contact == "customer@example.com"
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
    assert fields["marketingConsent"].default == "false"


def test_transform_json_primitive_type():
    mdl = parse_text_to_ir("""
    domain example {
      owner: "test-team"
      entity Widget @ 1 (additive) {
        @key id: uuid
        payload: json
        tags: array<json>
        attributes: map<string, json>
      }
    }
    """)

    fields = {f.name: f for f in mdl.domains[0].models["Widget"][0].fields}
    assert fields["payload"].type.kind == "json"
    assert fields["tags"].type.item.kind == "json"
    assert fields["attributes"].type.value.kind == "json"


def test_transform_projection():
    mdl = parse_text_to_ir("""
    domain billing {
      owner: "test-team"
      projection BillingCustomer @ 1
        from customer.Customer @ 2 as c
        left join orders.Order @ 3 as o on c.customerId == o.customerId
        where c.status == "active"
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
    assert projection.source.where == 'c.status == "active"'
    assert projection.joins[0].join_kind == "left"
    fields = {field.name: field for field in projection.fields}
    assert fields["billingCustomerId"].mapping.kind == "direct"
    assert fields["billingCustomerId"].mapping.source_alias == "c"
    assert fields["billingCustomerId"].mapping.source_field == "customerId"
    assert fields["isBillable"].mapping.kind == "computed"
    assert "c.status" in fields["isBillable"].mapping.expression


def test_transform_version_range():
    mdl = parse_text_to_ir("""
    domain billing {
      owner: "test-team"
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


def test_transform_auto_projection_declaration():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
      }

      auto projections Customer @ 1 {
        db
        request
        reply
        event
      }
    }
    """)

    domain = mdl.domains[0]
    auto_projection = domain.auto_projections[0]
    assert auto_projection.model == "Customer"
    assert auto_projection.version == 1
    assert [target.kind for target in auto_projection.targets] == [
        "db",
        "request",
        "reply",
        "event",
    ]


def test_transform_classification_annotation():
    mdl = parse_text_to_ir("""
    domain payments {
      owner: "test-team"
      entity Payment @ 1 (additive) {
        @key paymentId: uuid
        @classification("secret") cardNumber: string
        @classification("internal") amount: decimal(10, 2)
        @classification("open") currency: string
        @classification("confidential") customerId: uuid
      }
    }
    """)

    fields = {f.name: f for f in mdl.domains[0].models["Payment"][0].fields}
    assert fields["cardNumber"].classification == ClassificationLevel.secret
    assert fields["amount"].classification == ClassificationLevel.internal
    assert fields["currency"].classification == ClassificationLevel.open
    assert fields["customerId"].classification == ClassificationLevel.confidential
    assert fields["paymentId"].classification is None


def test_transform_classification_on_projection_field():
    mdl = parse_text_to_ir("""
    domain payments {
      owner: "test-team"
      projection PaymentSummary @ 1
        from payments.Payment @ 1 as p
      {
        @classification("confidential") customerId <- p.customerId
        amount <- p.amount
      }
    }
    """)

    fields = {f.name: f for f in mdl.domains[0].projections["PaymentSummary"][0].fields}
    assert fields["customerId"].classification == ClassificationLevel.confidential
    assert fields["amount"].classification is None


def test_transform_access_block():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        access {
          entity billing [read, project, subscribe]
          property email billing [read]
        }
        email?: string
      }
    }
    """)

    version = mdl.domains[0].models["Customer"][0]
    assert version.access is not None
    assert [grant.principal for grant in version.access.entity] == ["billing"]
    assert version.access.entity[0].permissions == ["read", "project", "subscribe"]
    assert version.access.properties["email"][0].principal == "billing"
    assert version.access.properties["email"][0].permissions == ["read"]


def test_transform_projection_access_block():
    mdl = parse_text_to_ir("""
    domain billing {
      owner: "test-team"
      projection BillingCustomer @ 1
        from customer.Customer @ 1 as c
      {
        access {
          entity billing [read, project]
        }
        customerId <- c.customerId
      }
    }
    """)

    version = mdl.domains[0].projections["BillingCustomer"][0]
    assert version.access is not None
    assert [grant.principal for grant in version.access.entity] == ["billing"]
    assert version.access.entity[0].permissions == ["read", "project"]


def test_transform_workspace_metadata():
    mdl = parse_text_to_ir("""
    workspace "analytics-platform" {
      name: "analytics-platform"
      description: "Analytics registry"
      generate {
        docs -> "./generated/docs/"
        sql(postgres) -> "./generated/sql/"
      }
    }
    """)

    assert mdl.workspace is not None
    assert mdl.workspace.label == "analytics-platform"
    assert mdl.workspace.name == "analytics-platform"
    assert mdl.workspace.description == "Analytics registry"
    assert [target.name for target in mdl.workspace.generate_targets] == ["docs", "sql"]


def test_transform_fixture_files(fixture_path):
    from modelable.parser.parse import parse_file_to_ir

    customer_mdl = parse_file_to_ir(fixture_path / "customer.mdl")
    assert customer_mdl.domains[0].name == "customer"
    billing_mdl = parse_file_to_ir(fixture_path / "billing_projection.mdl")
    assert "BillingCustomer" in billing_mdl.domains[0].projections
