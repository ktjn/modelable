from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.emitters.openmetadata import emit_openmetadata
from modelable.emitters.openmetadata_plan import emit_openmetadata_projection_plan
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA, load_plan


def test_openmetadata_emitter_requests_v1_plan_documents(monkeypatch, tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) { @key customerId: uuid }
  projection CustomerSummary @ 1 from customer.Customer @ 1 as c { customerId <- c.customerId }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    observed: list[dict[str, str]] = []

    def observe_plan_request(workspace, **kwargs):
        observed.append(kwargs)
        return build_plan_documents(workspace, **kwargs)

    monkeypatch.setattr("modelable.emitters.openmetadata.build_plan_documents", observe_plan_request)

    emit_openmetadata(workspace, tmp_path / "out")

    assert observed == [{"schema": PLAN_V1_SCHEMA}]


def test_emit_openmetadata(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  description: "Manage customers and accounts"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii
    @classification("confidential")
    @owner("identity-team")
    email: string
    name: string
  }

  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
    email <- c.email
    displayName = c.name
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_openmetadata(workspace, tmp_path / "out")

    # Verify artifacts
    assert len(artifacts) == 1  # Only one domain

    art = artifacts[0]
    assert art.target == "openmetadata"
    assert art.ref == "customer"

    # Parse json
    data = art.content
    assert data["name"] == "customer"
    assert data["description"] == "Manage customers and accounts"
    assert data["owner"] == "customer-team"
    assert len(data["assets"]) == 2

    model_asset = next(asset for asset in data["assets"] if asset["name"] == "Customer")
    assert model_asset["kind"] == "entity"
    assert model_asset["version"] == 1
    assert model_asset["fullyQualifiedName"] == "modelable.customer.Customer.v1"
    assert model_asset["fields"] == [
        {
            "name": "customerId",
            "type": "uuid",
            "required": True,
            "key": True,
            "pii": False,
            "classification": None,
            "owner": None,
        },
        {
            "name": "email",
            "type": "string",
            "required": True,
            "key": False,
            "pii": True,
            "classification": "confidential",
            "owner": "identity-team",
        },
        {
            "name": "name",
            "type": "string",
            "required": True,
            "key": False,
            "pii": False,
            "classification": None,
            "owner": None,
        },
    ]

    projection_asset = next(asset for asset in data["assets"] if asset["name"] == "CustomerSummary")
    assert projection_asset["kind"] == "projection"
    assert projection_asset["version"] == 1
    assert projection_asset["fullyQualifiedName"] == "modelable.customer.CustomerSummary.v1"
    assert projection_asset["source"] == {
        "model": "customer.Customer",
        "version": {"kind": "exact", "version": 1},
        "alias": "c",
    }
    assert projection_asset["fields"] == [
        {
            "name": "customerId",
            "mapping": "direct",
            "source": "customer.Customer@1.customerId",
            "pii": False,
            "classification": None,
        },
        {
            "name": "name",
            "mapping": "direct",
            "source": "customer.Customer@1.name",
            "pii": False,
            "classification": None,
        },
        {
            "name": "email",
            "mapping": "direct",
            "source": "customer.Customer@1.email",
            "pii": True,
            "classification": "confidential",
        },
        {
            "name": "displayName",
            "mapping": "computed",
            "expression": "c.name",
            "pii": False,
            "classification": None,
        },
    ]
    assert data["lineage"] == [
        {
            "from": "modelable.customer.Customer.v1.customerId",
            "to": "modelable.customer.CustomerSummary.v1.customerId",
            "kind": "direct",
        },
        {
            "from": "modelable.customer.Customer.v1.name",
            "to": "modelable.customer.CustomerSummary.v1.name",
            "kind": "direct",
        },
        {
            "from": "modelable.customer.Customer.v1.email",
            "to": "modelable.customer.CustomerSummary.v1.email",
            "kind": "direct",
        },
    ]


def test_openmetadata_projection_consumer_uses_validated_plan_data(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "plan_v0" / "billing.BillingCustomer.v1.plan.json"
    plan = load_plan(fixture)

    asset, lineage = emit_openmetadata_projection_plan(plan)

    assert asset == {
        "name": "BillingCustomer",
        "kind": "projection",
        "version": 1,
        "fullyQualifiedName": "modelable.billing.BillingCustomer.v1",
        "source": {"model": "customer.Customer", "version": {"kind": "exact", "version": 1}, "alias": "c"},
        "fields": [
            {
                "name": "billingId",
                "mapping": "direct",
                "source": "customer.Customer@1.customerId",
                "pii": False,
                "classification": None,
            }
        ],
    }
    assert lineage == [
        {
            "from": "modelable.customer.Customer.v1.customerId",
            "to": "modelable.billing.BillingCustomer.v1.billingId",
            "kind": "direct",
        }
    ]


def test_openmetadata_projection_consumer_preserves_join_source_and_filter_facts(tmp_path):
    (tmp_path / "joined.mdl").write_text(
        """
domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) { @key customerId: uuid }
}
domain account {
  owner: "account-team"
  entity Account @ 2 (additive) { @key accountId: uuid name: string }
}
domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ >=1<3 as c
    left join account.Account @ >=2<4 as a on c.customerId == a.accountId
    cardinality: many
    where c.customerId != null
  {
    accountName <- a.name
  }
}
""".strip(),
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    assert workspace.errors == []
    plan = next(plan for plan in build_plan_documents(workspace) if plan["domain"] == "billing")

    asset, lineage = emit_openmetadata_projection_plan(plan)

    assert asset["source"] == {
        "model": "customer.Customer",
        "version": {"kind": "range", "minInclusive": 1, "maxExclusive": 3},
        "alias": "c",
    }
    assert asset["where"] == "c.customerId != null"
    assert asset["joins"] == [
        {
            "model": "account.Account",
            "version": {"kind": "range", "minInclusive": 2, "maxExclusive": 4},
            "alias": "a",
            "on": "c.customerId == a.accountId",
            "kind": "left",
            "cardinality": "many",
        }
    ]
    assert asset["fields"] == [
        {
            "name": "accountName",
            "mapping": "direct",
            "source": "account.Account@>=2<4.name",
            "pii": False,
            "classification": None,
        }
    ]
    assert lineage == [
        {
            "from": "modelable.account.Account.v2.name",
            "to": "modelable.billing.BillingCustomer.v1.accountName",
            "kind": "direct",
        }
    ]


def test_openmetadata_plan_consumer_imports_without_parser_modules() -> None:
    source_root = Path(__file__).parents[1] / "src"
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.startswith('modelable.parser'):
        raise AssertionError('OpenMetadata plan consumer imported parser internals')
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
from modelable.emitters.openmetadata_plan import emit_openmetadata_projection_plan
assert emit_openmetadata_projection_plan
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
