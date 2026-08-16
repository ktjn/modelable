import pytest

from modelable.compat.checker import (
    ApiCompatibilityReport,
    CompatibilityReport,
    ProjectionCompatibilityReport,
    analyze_impact,
    check_api_version_compatibility,
    check_model_version_compatibility,
    check_projection_version_compatibility,
)
from modelable.parser.parse import parse_text_to_ir


def test_api_compatibility_reports_operation_contract_changes() -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses {
        200: CustomerReply @ 1
        404: ProblemDetails @ 1
      }
    }
    operation "legacyCustomer" {
      method: GET
      path: "/customers/legacy"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
  api Customer @ 2 {
    operation "getCustomer" {
      method: POST
      path: "/customers/{customer_id}"
      responses {
        200: CustomerReply @ 1
        201: CustomerReply @ 1
      }
    }
    operation "fetchCustomer" {
      method: GET
      path: "/customers/legacy"
      responses {
        200: CustomerReply @ 1
      }
    }
    operation "newCustomer" {
      method: GET
      path: "/customers/new"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
}
"""
    )

    report = check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    assert isinstance(report, ApiCompatibilityReport)
    assert report.status == "breaking"
    assert [(change.kind, change.subject, change.breaking) for change in report.changes] == [
        ("operation_renamed", "legacyCustomer", True),
        ("operation_added", "newCustomer", False),
        ("method_changed", "getCustomer", True),
        ("path_changed", "getCustomer", True),
        ("path_key_renamed", "getCustomer", True),
        ("response_removed", "getCustomer", True),
        ("response_added", "getCustomer", False),
    ]


def test_api_compatibility_accepts_added_operations_and_responses() -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
  api Customer @ 2 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses {
        200: CustomerReply @ 1
        404: ProblemDetails @ 1
      }
    }
    operation "health" {
      method: GET
      path: "/health"
      responses {
        200: HealthReply @ 1
      }
    }
  }
}
"""
    )

    report = check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    assert report.status == "compatible"
    assert [change.kind for change in report.changes] == ["operation_added", "response_added"]


def test_api_compatibility_reports_path_key_type_changes() -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
  entity Customer @ 2 (breaking) {
    @key id: string
  }
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
  api Customer @ 2 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
}
"""
    )

    report = check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    assert report.status == "breaking"
    assert [(change.kind, change.subject) for change in report.changes] == [("path_key_type_changed", "getCustomer")]


def test_api_compatibility_reports_removed_operation_and_request_contract_changes() -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  api Customer @ 1 {
    operation "legacy" {
      method: GET
      path: "/legacy"
      responses {
        200: CustomerReply @ 1
      }
    }
    operation "createCustomer" {
      method: POST
      path: "/customers"
      responses {
        201: CustomerReply @ 1
      }
    }
  }
  api Customer @ 2 {
    operation "createCustomer" {
      method: POST
      path: "/customers"
      request: CustomerRequest @ 1
      responses {
        201: CustomerReply @ 1
      }
    }
  }
}
"""
    )

    report = check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    assert [(change.kind, change.subject, change.breaking) for change in report.changes] == [
        ("operation_removed", "legacy", True),
        ("request_changed", "createCustomer", True),
    ]


def test_api_compatibility_reports_changed_request_projection_name() -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  api Customer @ 1 {
    operation "createCustomer" {
      method: POST
      path: "/customers"
      request: CustomerRequest @ 1
      responses {
        201: CustomerReply @ 1
      }
    }
  }
  api Customer @ 2 {
    operation "createCustomer" {
      method: POST
      path: "/customers"
      request: CustomerUpdate @ 1
      responses {
        201: CustomerReply @ 1
      }
    }
  }
}
"""
    )

    report = check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    assert report.status == "breaking"
    assert report.changes[0].kind == "request_changed"


@pytest.mark.parametrize("status", ["compatible", "breaking"])
def test_api_compatibility_delegates_same_projection_version_changes(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
  api Customer @ 2 {
    operation "getCustomer" {
      method: GET
      path: "/customers"
      responses {
        200: CustomerReply @ 2
      }
    }
  }
}
"""
    )
    delegated = ProjectionCompatibilityReport("Billing", "CustomerReply", 1, 2, status)
    monkeypatch.setattr("modelable.compat.checker.check_projection_version_compatibility", lambda *args: delegated)

    report = check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    assert report.status == status
    assert report.changes[0].kind == "response_changed"


def test_api_compatibility_delegates_changed_request_projection_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  api Customer @ 1 {
    operation "createCustomer" {
      method: POST
      path: "/customers"
      request: CustomerRequest @ 1
      responses {
        201: CustomerReply @ 1
      }
    }
  }
  api Customer @ 2 {
    operation "createCustomer" {
      method: POST
      path: "/customers"
      request: CustomerRequest @ 2
      responses {
        201: CustomerReply @ 1
      }
    }
  }
}
"""
    )
    delegated = ProjectionCompatibilityReport("Billing", "CustomerRequest", 1, 2, "compatible")
    monkeypatch.setattr("modelable.compat.checker.check_projection_version_compatibility", lambda *args: delegated)

    report = check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    assert report.status == "compatible"
    assert report.changes[0].message.endswith("changed (compatible)")


def test_api_compatibility_reports_response_projection_replacement() -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
  api Customer @ 2 {
    operation "getCustomer" {
      method: GET
      path: "/customers"
      responses {
        200: CustomerDetails @ 1
      }
    }
  }
}
"""
    )

    report = check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    assert report.status == "breaking"
    assert report.changes[0].message.endswith("changed (breaking)")


def test_api_compatibility_rejects_unknown_api_version() -> None:
    mdl = parse_text_to_ir("domain Billing { }")

    with pytest.raises(LookupError, match="unknown API version"):
        check_api_version_compatibility(mdl, "Billing", "Customer", 1, 2)

    with pytest.raises(LookupError, match="unknown API version"):
        check_api_version_compatibility(mdl, "Other", "Customer", 1, 2)


def test_projection_and_model_compatibility_cover_empty_domain_metadata() -> None:
    mdl = parse_text_to_ir(
        """
domain Billing {
  entity Customer @ 1 (additive) {
    id: string
  }
  entity Customer @ 2 (additive) {
    id: string
  }
}
"""
    )

    model_report = check_model_version_compatibility(mdl, "Billing", "Customer", 1, 2)
    assert model_report.status == "compatible"

    with pytest.raises(LookupError, match="unknown projection version"):
        check_projection_version_compatibility(mdl, "Other", "CustomerView", 1, 2)


def test_analyze_impact_reports_unresolved_projection() -> None:
    mdl = parse_text_to_ir("domain Billing { }")
    report = CompatibilityReport("Billing", "Customer", 1, 2, "breaking")

    impact = analyze_impact(mdl, report, ("Billing", "CustomerView", 1))

    assert impact.status == "affected"
    assert impact.reason == "unresolved projection"
