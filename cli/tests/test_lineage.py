import copy
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from modelable.compiler.workspace import Workspace, load_workspace
from modelable.parser.parse import parse_text_to_ir
from modelable.planner.lineage import _expand_lineage_ref, build_projection_lineage
from modelable.planner.plans import build_plan, build_plan_documents, write_plans
from modelable.planner.protocol import PLAN_V1_SCHEMA, PlanProtocolError, load_plan, serialize_plan, validate_plan

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


def _load_ws(mdl_text: str) -> Workspace:
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
    assert "customer.Customer@1#customerId" in by_name["billingId"].lineage


def test_direct_mapping_resolves_alias():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)

    by_name = {fl.field_name: fl for fl in lineage.fields}
    assert "customer.Customer@1#legalName" in by_name["name"].lineage


# ── Computed mapping lineage ───────────────────────────────────────────────────


def test_computed_mapping_lineage():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)

    by_name = {fl.field_name: fl for fl in lineage.fields}
    assert by_name["isActive"].kind == "computed"
    assert "customer.Customer@1#status" in by_name["isActive"].lineage


def test_computed_mapping_stores_expression():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)

    by_name = {fl.field_name: fl for fl in lineage.fields}
    assert by_name["isActive"].expression is not None
    assert "c.status" in by_name["isActive"].expression


def test_projection_lineage_resolves_through_projection_sources() -> None:
    fixture = Path(__file__).parent / "fixtures" / "materialized_projection_chain.mdl"
    mdl = parse_text_to_ir(fixture.read_text(encoding="utf-8"))
    pv = mdl.domains[1].projections["CustomerMart"][0]

    lineage = build_projection_lineage("analytics", "CustomerMart", pv, mdl)

    by_name = {item.field_name: item for item in lineage.fields}
    assert by_name["customerId"].lineage == ["customer.Customer@1#customerId"]
    assert by_name["displayName"].lineage == ["customer.Customer@1#legalName"]


def test_projection_lineage_expands_computed_projection_fields() -> None:
    mdl = parse_text_to_ir(
        textwrap.dedent(
            """
            domain customer {
              owner: "customer-platform"
              entity Customer @ 1 (additive) { name: string }
            }
            domain analytics {
              owner: "analytics-platform"
              projection CustomerFlags @ 1 from customer.Customer @ 1 as c {
                hasName = c.name != ""
              }
              projection CustomerSummary @ 1 from analytics.CustomerFlags @ 1 as f {
                hasName <- f.hasName
              }
            }
            """
        )
    )
    pv = mdl.domains[1].projections["CustomerSummary"][0]

    lineage = build_projection_lineage("analytics", "CustomerSummary", pv, mdl)

    assert lineage.fields[0].lineage == ["customer.Customer@1#name"]


def test_projection_lineage_stops_on_unresolved_cycle_or_field() -> None:
    fixture = Path(__file__).parent / "fixtures" / "materialized_projection_chain.mdl"
    mdl = parse_text_to_ir(fixture.read_text(encoding="utf-8"))

    assert _expand_lineage_ref("missing.Missing@1", "field", mdl, stack=()) == ["missing.Missing@1#field"]
    assert _expand_lineage_ref("analytics.CustomerOds@1", "missing", mdl, stack=()) == [
        "analytics.CustomerOds@1#missing"
    ]
    assert _expand_lineage_ref(
        "analytics.CustomerOds@1",
        "customerId",
        mdl,
        stack=(("analytics.CustomerOds@1", "customerId"),),
    ) == ["analytics.CustomerOds@1#customerId"]


# ── Plan document structure ────────────────────────────────────────────────────


def test_plan_document_structure():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    assert plan["$schema"] == PLAN_V1_SCHEMA == "modelable.plan/v1"
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
    assert plan["source"]["resolved"]["domain"] == "customer"
    assert plan["source"]["resolved"]["kind"] == "model"
    assert plan["source"]["resolved"]["model_kind"] == "entity"
    assert plan["source"]["resolved"]["fields"][0]["name"] == "customerId"
    assert plan["source"]["version"] == {"kind": "exact", "version": 1}
    assert plan["joins"] == []
    assert plan["group_by"] == []
    assert "fields" in plan
    assert "planner_metadata" in plan


def test_plan_document_preserves_projection_filter_and_join_facts() -> None:
    mdl = parse_text_to_ir(
        textwrap.dedent(
            """
            domain customer {
              owner: "test-team"
              entity Customer @ 1 (additive) { @key customerId: uuid }
            }
            domain account {
              owner: "test-team"
              entity Account @ 2 (additive) { @key accountId: uuid }
            }
            domain billing {
              owner: "test-team"
              projection BillingCustomer @ 1
                from customer.Customer @ >=1<3 as c
                left join account.Account @ >=2<4 as a on c.customerId = a.accountId
                cardinality: many
                where c.customerId != null
              {
                billingId <- c.customerId
              }
            }
            """
        )
    )
    pv = mdl.domains[2].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    assert plan["source"]["version"] == {"kind": "range", "minInclusive": 1, "maxExclusive": 3}
    assert plan["where"] == "c.customerId != null"
    assert len(plan["joins"]) == 1
    join = plan["joins"][0]
    assert join["model"] == "account.Account"
    assert join["version"] == {"kind": "range", "minInclusive": 2, "maxExclusive": 4}
    assert join["resolved_version"] == 2
    assert join["on"] == "c.customerId = a.accountId"
    assert join["kind"] == "left"
    assert join["cardinality"] == "many"


def test_plan_field_kinds():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    by_name = {f["name"]: f for f in plan["fields"]}
    assert by_name["billingId"]["kind"] == "direct"
    assert by_name["billingId"]["source_alias"] == "c"
    assert by_name["billingId"]["source_field"] == "customerId"
    assert by_name["billingId"]["type"] == {"kind": "uuid", "version": 4}
    assert by_name["billingId"]["optional"] is False
    assert by_name["isActive"]["kind"] == "computed"
    assert "expression" in by_name["isActive"]
    assert by_name["isActive"]["type"] is None
    assert by_name["isActive"]["optional"] is None


def test_plan_includes_lineage():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    by_name = {f["name"]: f for f in plan["fields"]}
    assert "customer.Customer@1#customerId" in by_name["billingId"]["lineage"]
    assert "customer.Customer@1#status" in by_name["isActive"]["lineage"]


def test_build_plan_can_emit_v1_documents():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)

    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl, schema=PLAN_V1_SCHEMA)

    assert plan["$schema"] == PLAN_V1_SCHEMA
    assert validate_plan(plan) == plan


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
        assert data["$schema"] == PLAN_V1_SCHEMA
        assert load_plan(path) == data


def test_write_plans_can_emit_v1_documents(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    mdl_path.write_text(_MDL, encoding="utf-8")
    ws = load_workspace(tmp_path)

    written = write_plans(ws, tmp_path / "plans", schema=PLAN_V1_SCHEMA)

    assert written
    assert all(json.loads(path.read_text(encoding="utf-8"))["$schema"] == PLAN_V1_SCHEMA for path in written)


def test_build_plan_documents_are_sorted_by_canonical_identity(tmp_path: Path) -> None:
    (tmp_path / "models.mdl").write_text(_MDL, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    documents = build_plan_documents(workspace, schema=PLAN_V1_SCHEMA)
    identities = [(document["domain"], document["projection"], document["version"]) for document in documents]

    assert identities == sorted(identities)


def test_plan_protocol_serialization_is_deterministic(tmp_path):
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    reordered = dict(reversed(list(plan.items())))
    assert serialize_plan(plan) == serialize_plan(reordered)
    assert validate_plan(json.loads(serialize_plan(plan))) == plan


def test_plan_protocol_fixture_round_trips():
    fixture = Path(__file__).parent / "fixtures" / "plan_v0" / "billing.BillingCustomer.v1.plan.json"
    loaded = load_plan(fixture)
    assert serialize_plan(loaded) == fixture.read_text(encoding="utf-8")


def test_plan_protocol_rejects_unsupported_schema(tmp_path):
    path = tmp_path / "invalid.plan.json"
    path.write_text(json.dumps({"$schema": "modelable.plan/v2"}), encoding="utf-8")
    with pytest.raises(PlanProtocolError, match="unsupported plan schema"):
        load_plan(path)


def test_plan_protocol_rejects_invalid_structure():
    mdl = parse_text_to_ir(_MDL)
    pv = mdl.domains[1].projections["BillingCustomer"][0]
    lineage = build_projection_lineage("billing", "BillingCustomer", pv, mdl)
    plan = build_plan("billing", "BillingCustomer", pv, lineage, mdl)

    invalid_cases = (
        ("version", True, "version"),
        ("extra", "unexpected", "unknown"),
        ("revalidation", True, "requires_revalidation"),
    )
    for name, value, message in invalid_cases:
        candidate = copy.deepcopy(plan)
        if name == "extra":
            candidate[name] = value
        elif name == "revalidation":
            candidate["requires_revalidation"] = value
        else:
            candidate[name] = value
        with pytest.raises(PlanProtocolError, match=message):
            validate_plan(candidate)

    duplicate_fields = copy.deepcopy(plan)
    duplicate_fields["fields"].append(copy.deepcopy(duplicate_fields["fields"][0]))
    with pytest.raises(PlanProtocolError, match="duplicate name"):
        validate_plan(duplicate_fields)

    invalid_declaration = copy.deepcopy(plan)
    invalid_declaration["source"]["resolved"]["model_kind"] = "not-a-model-kind"
    with pytest.raises(PlanProtocolError, match="model_kind"):
        validate_plan(invalid_declaration)

    mismatched_declaration = copy.deepcopy(plan)
    mismatched_declaration["source"]["resolved"]["name"] = "OtherCustomer"
    with pytest.raises(PlanProtocolError, match="identity"):
        validate_plan(mismatched_declaration)

    mismatched_version = copy.deepcopy(plan)
    mismatched_version["source"]["version"]["version"] = 2
    with pytest.raises(PlanProtocolError, match="requested version"):
        validate_plan(mismatched_version)

    unknown_alias = copy.deepcopy(plan)
    unknown_alias["fields"][0]["source_alias"] = "missing"
    with pytest.raises(PlanProtocolError, match="relation"):
        validate_plan(unknown_alias)

    unknown_field = copy.deepcopy(plan)
    unknown_field["fields"][0]["source_field"] = "missing"
    with pytest.raises(PlanProtocolError, match="present"):
        validate_plan(unknown_field)

    unresolved_with_version = copy.deepcopy(plan)
    unresolved_with_version["source"]["resolved"] = None
    with pytest.raises(PlanProtocolError, match="resolved_version"):
        validate_plan(unresolved_with_version)


def test_plan_protocol_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "duplicate.plan.json"
    path.write_text('{"$schema":"modelable.plan/v0","$schema":"modelable.plan/v0"}', encoding="utf-8")
    with pytest.raises(PlanProtocolError, match="Duplicate JSON key"):
        load_plan(path)


def test_plan_protocol_rejects_non_finite_json_numbers(tmp_path):
    path = tmp_path / "non-finite.plan.json"
    path.write_text('{"version":NaN}', encoding="utf-8")
    with pytest.raises(PlanProtocolError, match="Non-finite"):
        load_plan(path)


def test_plan_protocol_imports_without_parser_modules():
    source_root = Path(__file__).parents[1] / "src"
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.startswith('modelable.parser'):
        raise AssertionError('protocol imported parser internals')
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
from modelable.planner.protocol import PLAN_SCHEMA
assert PLAN_SCHEMA == 'modelable.plan/v0'
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_write_plans_file_naming(tmp_path):
    mdl_path = tmp_path / "test.mdl"
    mdl_path.write_text(_MDL, encoding="utf-8")
    ws = load_workspace(tmp_path)

    plans_dir = tmp_path / "plans"
    write_plans(ws, plans_dir)

    expected = plans_dir / "billing.BillingCustomer.v1.plan.json"
    assert expected.exists()


def test_write_plans_supports_projection_sources(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "projection_of_projection.mdl"
    ws = load_workspace(fixture)
    assert ws.errors == []

    written = write_plans(ws, tmp_path / "plans")
    summary = json.loads(next(path for path in written if "Summary" in path.name).read_text(encoding="utf-8"))
    assert summary["source"]["resolved"]["kind"] == "projection"
    assert summary["source"]["resolved"]["model_kind"] is None
    assert summary["source"]["resolved"]["fields"][0]["type"] == {"kind": "uuid", "version": 4}
    assert summary["source"]["resolved"]["fields"][0]["nullable"] is False


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
