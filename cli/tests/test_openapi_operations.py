from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.openapi import emit_openapi
from modelable.parser.parse import parse_text_to_ir


def test_parse_api_operations_and_responses() -> None:
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
  }
}
"""
    )

    api = mdl.domains[0].apis[0]
    assert api.model == "Customer"
    assert api.version == 1
    assert api.operations[0].method == "GET"
    assert api.operations[0].path == "/customers/{id}"
    assert api.operations[0].request is None
    assert [(item.status_code, item.projection, item.version) for item in api.operations[0].responses] == [
        (200, "CustomerReply", 1),
        (404, "ProblemDetails", 1),
    ]

    rendered = render_mdl(mdl)
    assert 'operation "getCustomer" {' in rendered
    assert 'path: "/customers/{id}"' in rendered


def test_workspace_validates_api_path_keys_and_projection_versions() -> None:
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="memory://api.mdl",
                text="""
domain Billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key id: uuid
    name: string
  }
  auto projections Customer @ 1 {
    request
    reply
  }
  api Customer @ 1 {
    operation "getCustomer" {
      method: GET
      path: "/customers/{missing}"
      responses {
        200: CustomerReply @ 2
      }
    }
  }
}
""",
            )
        ]
    )

    messages = [error.message for error in workspace.errors]
    assert any("path parameter(s) not found among model keys: missing" in message for message in messages)
    assert any("response projection Billing.CustomerReply@2 does not exist" in message for message in messages)


def test_emit_openapi_includes_paths_and_json_bindings(tmp_path) -> None:
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="memory://api.mdl",
                text="""
domain Billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key id: uuid
    name: string
  }
  auto projections Customer @ 1 {
    request
    reply
  }
  api Customer @ 1 {
    operation "createCustomer" {
      method: POST
      path: "/customers"
      request: CustomerRequest @ 1
      responses {
        201: CustomerReply @ 1
      }
    }
    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses {
        200: CustomerReply @ 1
      }
    }
  }
}
""",
            )
        ]
    )

    assert workspace.errors == []
    document = emit_openapi(workspace, tmp_path)[0].content
    assert list(document["paths"]) == ["/customers", "/customers/{id}"]
    create = document["paths"]["/customers"]["post"]
    assert create["operationId"] == "createCustomer"
    assert create["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("Billing.CustomerRequest.v1")
    get = document["paths"]["/customers/{id}"]["get"]
    assert get["parameters"][0]["name"] == "id"
    assert get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("Billing.CustomerReply.v1")


def test_emit_openapi_preserves_all_composite_key_path_parameters(tmp_path) -> None:
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="memory://api.mdl",
                text="""
domain Billing {
  owner: "billing"
  entity OrderLine @ 1 (additive) {
    @key orderId: uuid
    @key lineNumber: int
  }
  projection OrderLineReply @ 1 from Billing.OrderLine @ 1 as line {
    orderId <- line.orderId
    lineNumber <- line.lineNumber
  }
  api OrderLine @ 1 {
    operation "getOrderLine" {
      method: GET
      path: "/orders/{orderId}/lines/{lineNumber}"
      responses {
        200: OrderLineReply @ 1
      }
    }
  }
}
""",
            )
        ]
    )

    assert workspace.errors == []
    document = emit_openapi(workspace, tmp_path)[0].content
    parameters = document["paths"]["/orders/{orderId}/lines/{lineNumber}"]["get"]["parameters"]

    assert [parameter["name"] for parameter in parameters] == ["orderId", "lineNumber"]
