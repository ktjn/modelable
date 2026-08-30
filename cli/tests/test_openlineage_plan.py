import json
from copy import deepcopy
from pathlib import Path

from modelable.emitters.openlineage_plan import emit_openlineage_plan
from modelable.planner.protocol import load_plan


def test_openlineage_plan_consumer_uses_only_plan_data(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "plan_v0" / "billing.BillingCustomer.v1.plan.json"
    artifact = emit_openlineage_plan(load_plan(fixture), tmp_path)

    assert artifact.target == "openlineage"
    assert artifact.ref == "billing.BillingCustomer@1"
    assert artifact.path == tmp_path / "billing.BillingCustomer.v1.openlineage.json"
    event = artifact.content
    assert event["inputs"][0]["name"] == "customer.Customer.v1"
    assert event["outputs"][0]["facets"]["schema"]["fields"] == [{"name": "billingId", "type": "uuid"}]

    rendered = json.dumps(event, sort_keys=True)
    assert "customer.Customer.v1" in rendered


def test_openlineage_plan_consumer_emits_resolved_joins_and_type_shapes(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "plan_v0" / "billing.BillingCustomer.v1.plan.json"
    plan = deepcopy(load_plan(fixture))
    plan["joins"] = [
        {
            "model": "account.Account",
            "version": {"kind": "exact", "version": 2},
            "resolved_version": 2,
            "alias": "a",
            "change_kind": None,
            "resolved": {
                "domain": "account",
                "name": "Account",
                "version": 2,
                "kind": "model",
                "model_kind": "entity",
                "fields": [
                    {
                        "name": "accountId",
                        "type": {"kind": "enum_ref", "name": "AccountId", "version": 1},
                        "optional": False,
                        "nullable": False,
                        "pii": False,
                        "classification": None,
                        "owner": None,
                    }
                ],
            },
            "on": "c.accountId = a.accountId",
            "kind": "inner",
            "cardinality": None,
        }
    ]
    plan["fields"][0]["lineage"] = ["customer.Customer@1.customerId", "account.Account@2.accountId"]
    plan["fields"][0]["type"] = {"kind": "enum", "values": ["active", "inactive"]}
    plan["fields"][0]["pii"] = True
    plan["fields"][0]["classification"] = "confidential"
    plan["fields"][0]["owner"] = "billing-team"

    event = emit_openlineage_plan(plan, tmp_path).content

    assert [dataset["name"] for dataset in event["inputs"]] == ["customer.Customer.v1", "account.Account.v2"]
    assert event["inputs"][1]["facets"]["schema"]["fields"] == [{"name": "accountId", "type": "enumRef<AccountId@1>"}]
    assert event["outputs"][0]["facets"]["schema"]["fields"] == [
        {
            "name": "billingId",
            "type": "enum(active,inactive)",
            "description": "classification=confidential; pii=true; owner=billing-team",
        }
    ]
    assert event["outputs"][0]["facets"]["columnLineage"]["fields"]["billingId"]["inputFields"]
