from modelable.parser.parse import parse_text_to_ir
from modelable.planner.lineage import build_projection_lineage
from modelable.planner.plans import build_plan
from modelable.governance.checker import build_projection_governance_findings


def test_projection_without_access_block_emits_governance_findings():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
        }

        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            customerName = c.name
          }
        }
        """
    )

    pv = mdl.domains[1].projections["BillingCustomer"][0]
    findings = build_projection_governance_findings("billing", "BillingCustomer", pv, mdl)

    assert any(f.code == "missing_project_grant" for f in findings)
    assert any(f.code == "missing_read_grant" for f in findings)
    assert any(f.code == "missing_derivation_policy" for f in findings)


def test_projection_with_access_block_and_derivation_policy_passes():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            access {
              property name billing [read, derive]
            }
            name: string
          }
        }

        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            access {
              entity billing [read, project]
            }
            customerName = c.name
          }
        }
        """
    )

    pv = mdl.domains[1].projections["BillingCustomer"][0]
    findings = build_projection_governance_findings("billing", "BillingCustomer", pv, mdl)

    assert findings == []


def test_projection_missing_governance_metadata_emits_classification_findings():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            @pii
            @classification("restricted")
            secretToken: string
          }
        }

        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            access {
              entity billing [read, project]
            }
            token = c.secretToken
          }
        }
        """
    )

    pv = mdl.domains[1].projections["BillingCustomer"][0]
    findings = build_projection_governance_findings("billing", "BillingCustomer", pv, mdl)

    assert any(f.code == "missing_pii_metadata" for f in findings)
    assert any(f.code == "missing_classification_metadata" for f in findings)


def test_projection_lowering_classification_emits_governance_finding():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            @classification("restricted")
            secretToken: string
          }
        }

        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            access {
              entity billing [read, project]
            }
            @classification("internal")
            token = c.secretToken
          }
        }
        """
    )

    pv = mdl.domains[1].projections["BillingCustomer"][0]
    findings = build_projection_governance_findings("billing", "BillingCustomer", pv, mdl)

    assert any(f.code == "lowered_classification" for f in findings)


def test_plan_includes_governance_findings():
    mdl = parse_text_to_ir(
        """
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
        }

        domain billing {
          owner: "test-team"
          projection BillingCustomer @ 1
            from customer.Customer @ 1 as c
          {
            customerName = c.name
          }
        }
        """
    )

    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    assert "governance_findings" in plan
    assert any(finding["code"] == "missing_project_grant" for finding in plan["governance_findings"])
