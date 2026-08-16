from modelable.compat.checker import ApiCompatibilityReport, check_api_version_compatibility
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
