from pathlib import Path

from modelable.dependency_graph import PropertyDependency, build_projection_dependencies
from modelable.parser.ir import (
    DirectMapping,
    ProjectionField,
    ProjectionVersion,
    SourceRef,
    VersionMin,
    VersionPinned,
    VersionRange,
)
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.signature import compute_version_signature

FIXTURES = Path(__file__).parent / "fixtures"


def _billing_projection(mdl, name="BillingCustomer"):
    domain = next(d for d in mdl.domains if d.name == "billing")
    return domain.projections[name][0]


def test_direct_mapping_dependency():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            id <- c.customerId
          }
        }
        """
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", _billing_projection(mdl))

    assert deps == [
        PropertyDependency(
            consumer_ref="billing.BillingCustomer@1",
            target_property="id",
            usage_kind="direct",
            source_ref="customer.Customer@1",
            source_property="customerId",
        )
    ]


def test_computed_expression_dependency():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            isBillable = c.status == "active"
          }
        }
        """
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", _billing_projection(mdl))

    assert deps == [
        PropertyDependency(
            consumer_ref="billing.BillingCustomer@1",
            target_property="isBillable",
            usage_kind="computed",
            source_ref="customer.Customer@1",
            source_property="status",
        )
    ]


def test_join_predicate_dependency():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
        }
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection OrderWithCustomer @ 1
            from orders.Order @ 1 as o
            join customer.Customer @ 1 as c on o.customerId == c.customerId
          {
            orderId <- o.orderId
          }
        }
        """
    )

    deps = build_projection_dependencies(
        mdl, "billing", "OrderWithCustomer", _billing_projection(mdl, "OrderWithCustomer")
    )
    join_deps = [dep for dep in deps if dep.usage_kind == "join"]

    assert join_deps == [
        PropertyDependency(
            consumer_ref="billing.OrderWithCustomer@1",
            target_property=None,
            usage_kind="join",
            source_ref="orders.Order@1",
            source_property="customerId",
        ),
        PropertyDependency(
            consumer_ref="billing.OrderWithCustomer@1",
            target_property=None,
            usage_kind="join",
            source_ref="customer.Customer@1",
            source_property="customerId",
        ),
    ]


def test_where_filter_dependency():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
        }
        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
            left join orders.Order @ 1 as o on c.customerId == o.customerId
            where c.status == "active"
          {
            billingCustomerId <- c.customerId
          }
        }
        """
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", _billing_projection(mdl))
    filter_deps = [dep for dep in deps if dep.usage_kind == "filter"]

    assert filter_deps == [
        PropertyDependency(
            consumer_ref="billing.BillingCustomer@1",
            target_property=None,
            usage_kind="filter",
            source_ref="customer.Customer@1",
            source_property="status",
        )
    ]


def test_group_by_dependency():
    mdl = parse_text_to_ir(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
            totalAmount: decimal(10, 2)
          }
        }
        domain billing {
          owner: "test-team"
          projection CustomerOrderStats @ 1
            from orders.Order @ 1 as o
            group by o.customerId
          {
            customerId <- o.customerId
            totalSpent = sum(o.totalAmount)
          }
        }
        """
    )

    deps = build_projection_dependencies(
        mdl, "billing", "CustomerOrderStats", _billing_projection(mdl, "CustomerOrderStats")
    )
    group_deps = [dep for dep in deps if dep.usage_kind == "group"]

    assert group_deps == [
        PropertyDependency(
            consumer_ref="billing.CustomerOrderStats@1",
            target_property=None,
            usage_kind="group",
            source_ref="orders.Order@1",
            source_property="customerId",
        )
    ]


def test_range_source_resolves_to_highest_satisfying_version():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Customer @ 2 (additive) { @key customerId: uuid }
        }
        """
    )
    pv = ProjectionVersion(
        version=1,
        source=SourceRef(model="customer.Customer", version=VersionRange(min_inclusive=1, max_exclusive=3), alias="c"),
        fields=[ProjectionField(name="id", mapping=DirectMapping(source_alias="c", source_field="customerId"))],
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", pv)

    assert deps[0].source_ref == "customer.Customer@2"


def test_minimum_version_source_resolves_to_highest_available_version():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Customer @ 2 (additive) { @key customerId: uuid }
        }
        """
    )
    pv = ProjectionVersion(
        version=1,
        source=SourceRef(model="customer.Customer", version=VersionMin(min_inclusive=1), alias="c"),
        fields=[ProjectionField(name="id", mapping=DirectMapping(source_alias="c", source_field="customerId"))],
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", pv)

    assert deps[0].source_ref == "customer.Customer@2"


def test_pinned_source_resolves_when_signature_matches():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
        }
        """
    )
    v1 = mdl.domains[0].models["Customer"][0]
    signature = compute_version_signature("customer", "Customer", v1)
    pv = ProjectionVersion(
        version=1,
        source=SourceRef(
            model="customer.Customer", version=VersionPinned(version=1, content_hash=signature), alias="c"
        ),
        fields=[ProjectionField(name="id", mapping=DirectMapping(source_alias="c", source_field="customerId"))],
    )

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomer", pv)

    assert deps[0].source_ref == "customer.Customer@1"


def test_chained_projection_source_dependency():
    mdl = parse_text_to_ir((FIXTURES / "projection_of_projection.mdl").read_text())
    domain = next(d for d in mdl.domains if d.name == "billing")
    summary = domain.projections["BillingCustomerSummary"][0]

    deps = build_projection_dependencies(mdl, "billing", "BillingCustomerSummary", summary)

    # The chain is billing.BillingCustomerSummary -> billing.BillingCustomer -> customer.Customer.
    # This projection's own dependencies must resolve one hop, to the projection it sources
    # from directly, not flattened through to the root entity.
    assert all(dep.source_ref == "billing.BillingCustomer@1" for dep in deps)


def test_multi_source_property_usage():
    mdl = parse_text_to_ir((FIXTURES / "multi_domain_joins.mdl").read_text())
    domain = next(d for d in mdl.domains if d.name == "analytics")
    pv = domain.projections["CustomerOrderPayment"][0]

    deps = build_projection_dependencies(mdl, "analytics", "CustomerOrderPayment", pv)

    # orderTotal <- o.totalAmount (direct) and isFullyPaid = p.amount == o.totalAmount (computed)
    # both depend on orders.Order@1.totalAmount, via two different usage kinds.
    order_total_deps = [
        dep for dep in deps if dep.source_ref == "orders.Order@1" and dep.source_property == "totalAmount"
    ]
    assert {dep.usage_kind for dep in order_total_deps} == {"direct", "computed"}
    assert {dep.target_property for dep in order_total_deps} == {"orderTotal", "isFullyPaid"}
