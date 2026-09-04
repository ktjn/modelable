import json

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import dispatch_browser_request


def _dispatch(method: str, payload: object) -> dict:
    return json.loads(dispatch_browser_request(method, json.dumps(payload)))


def test_browser_query_uses_query_v1_service() -> None:
    browser_dispatch._reset_compiler_for_tests()
    opened = _dispatch(
        "workspace.open",
        {
            "workspaceRevision": 1,
            "sources": [
                {
                    "uri": "memory:///workspace.mdl",
                    "version": 1,
                    "text": 'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
                }
            ],
        },
    )
    assert opened["ok"] is True

    result = _dispatch(
        "workspace.query",
        {
            "workspaceRevision": 1,
            "request": {
                "$schema": "modelable.query/v1",
                "kind": "query",
                "query": "declaration",
                "id": "customer.Customer@1",
            },
        },
    )

    assert result["ok"] is True
    assert result["result"]["$schema"] == "modelable.query/v1"
    assert result["result"]["data"]["nodes"][0]["target_ref"] == "customer.Customer@1"
