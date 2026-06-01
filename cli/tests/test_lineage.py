import json
import textwrap

import pytest

from modelable.parser.parse import parse_text_to_ir
from modelable.planner.lineage import build_projection_lineage
from modelable.planner.plans import build_plan, write_plans
from modelable.compiler.workspace import load_workspace
from pathlib import Path
import tempfile


_MDL = textwrap.dedent("""\
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        legalName: string
        status: string
      }
    }
    domain billing {
      owner: "test-team"
      projection BillingCustomer @ 1
        from customer.Customer @ 1 as c
      {
        billingId <- c.customerId
        name <- c.legalName
        isActive = c.status == "active"
      }
    }
""")


def _load_ws(mdl_text: str) -> "Workspace":
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "test.mdl"
        p.write_text(mdl_text, encoding="utf-8")
        return load_workspace(tmp)


# ── Direct mapping lineage ─────────────────────────────────────────────────────


def test_direct_mapping_lineage():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)

    by_name = {fl.field_name: fl for fl in lineage.fields}
    assert by_name["billingId"].kind == "direct"
    assert "customer.Customer@1.customerId" in by_name["billingId"].lineage


def test_direct_mapping_resolves_alias():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)

    by_name = {fl.field_name: fl for fl in lineage.fields}
    assert "customer.Customer@1.legalName" in by_name["name"].lineage


# ── Computed mapping lineage ───────────────────────────────────────────────────


def test_computed_mapping_lineage():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)

    by_name = {fl.field_name: fl for fl in lineage.fields}
    assert by_name["isActive"].kind == "computed"
    assert "customer.Customer@1.status" in by_name["isActive"].lineage


def test_computed_mapping_stores_expression():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)

    by_name = {fl.field_name: fl for fl in lineage.fields}
    assert by_name["isActive"].expression is not None
    assert "c.status" in by_name["isActive"].expression


# ── Plan document structure ────────────────────────────────────────────────────


def test_plan_document_structure():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    assert plan["$schema"] == "modelable-plan/1.0"
    assert plan["domain"] == "billing"
    assert plan["projection"] == "BillingCustomer"
    assert plan["version"] == 1
    assert plan["auto_generated"] is False
    assert plan["requires_revalidation"] is False
    assert plan["revalidation_reasons"] == []
    assert plan["source"]["model"] == "customer.Customer"
    assert plan["source"]["resolved_version"] == 1
    assert plan["source"]["alias"] == "c"
    assert plan["source"]["change_kind"] == "additive"
    assert plan["joins"] == []
    assert plan["group_by"] == []
    assert "fields" in plan
    assert "planner_metadata" in plan


def test_plan_field_kinds():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    by_name = {f["name"]: f for f in plan["fields"]}
    assert by_name["billingId"]["kind"] == "direct"
    assert by_name["billingId"]["source_alias"] == "c"
    assert by_name["billingId"]["source_field"] == "customerId"
    assert by_name["isActive"]["kind"] == "computed"
    assert "expression" in by_name["isActive"]


def test_plan_includes_lineage():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    by_name = {f["name"]: f for f in plan["fields"]}
    assert "customer.Customer@1.customerId" in by_name["billingId"]["lineage"]
    assert "customer.Customer@1.status" in by_name["isActive"]["lineage"]


# ── Plan file writing ──────────────────────────────────────────────────────────


def test_write_plans_creates_files(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    mdl_path.write_text(_MDL, encoding="utf-8")
    ws = load_workspace(tmp_path)
    assert ws.errors == []

    plans_dir = tmp_path / "plans"
    written = write_plans(ws, plans_dir)
    assert len(written) > 0
    for path in written:
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["$schema"] == "modelable-plan/1.0"


def test_write_plans_file_naming(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    mdl_path.write_text(_MDL, encoding="utf-8")
    ws = load_workspace(tmp_path)

    plans_dir = tmp_path / "plans"
    write_plans(ws, plans_dir)

    expected = plans_dir / "billing.BillingCustomer.v1.plan.json"
    assert expected.exists()


def test_breaking_source_marks_plan_for_revalidation():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
      entity Customer @ 2 (breaking) {
        @key customerId: uuid
      }
    }

    domain billing {
      owner: "test-team"
      projection BillingCustomer @ 1
        from customer.Customer @ 2 as c
      {
        billingId <- c.customerId
      }
    }
    """)

    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    assert plan["requires_revalidation"] is True
    assert any("marked breaking" in reason for reason in plan["revalidation_reasons"])
