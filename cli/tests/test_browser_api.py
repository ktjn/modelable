import json

import pytest

from modelable.browser import (
    BrowserCompiler,
    BrowserSource,
    dispatch_browser_request,
)

VALID = 'domain customer {\n  owner: "team"\n  entity Customer @ 1 (additive) {\n    @key id: uuid\n  }\n}\n'


def test_open_workspace_returns_hashes_and_no_diagnostics():
    result = BrowserCompiler().open_workspace((BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=1),))

    assert result.diagnostics == ()
    assert set(result.source_hashes) == {"inmemory:///customer.mdl"}
    assert len(result.source_hashes["inmemory:///customer.mdl"]) == 64


def test_open_workspace_rejects_duplicate_uris():
    source = BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=1)

    with pytest.raises(ValueError, match="Source URIs must be unique"):
        BrowserCompiler().open_workspace((source, source))


def test_open_workspace_rejects_non_positive_versions():
    source = BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=0)

    with pytest.raises(
        ValueError,
        match=r"Source versions must be positive: inmemory:///customer\.mdl",
    ):
        BrowserCompiler().open_workspace((source,))


def test_open_workspace_returns_parse_error_for_the_source():
    source = BrowserSource(
        uri="inmemory:///broken.mdl",
        text="domain customer {",
        version=1,
    )

    result = BrowserCompiler().open_workspace((source,))

    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "PARSE"
    assert result.diagnostics[0].severity == "error"
    assert result.diagnostics[0].uri == "inmemory:///broken.mdl"
    assert result.diagnostics[0].line is not None
    assert result.source_hashes == {}


def test_open_workspace_preserves_semantic_diagnostic_source_order():
    first = BrowserSource(
        uri="inmemory:///first.mdl",
        text=('domain first {\n  owner: "team"\n  entity First @ 1 (additive) {\n    value: string\n  }\n}\n'),
        version=1,
    )
    second = BrowserSource(
        uri="inmemory:///second.mdl",
        text=('domain second {\n  owner: "team"\n  entity Second @ 1 (additive) {\n    value: string\n  }\n}\n'),
        version=1,
    )

    result = BrowserCompiler().open_workspace((first, second))

    assert [diagnostic.uri for diagnostic in result.diagnostics[:2]] == [
        first.uri,
        second.uri,
    ]
    assert all(diagnostic.severity == "error" for diagnostic in result.diagnostics)


def test_format_source_returns_canonical_text():
    source = BrowserSource(
        uri="inmemory:///customer.mdl",
        text='domain customer { owner: "team" }',
        version=1,
    )

    result = BrowserCompiler().format_source(source)

    assert result.diagnostics == ()
    assert result.replacement_text == 'domain customer {\n  owner: "team"\n}\n'


def test_format_source_is_blocked_by_semantic_errors():
    source = BrowserSource(
        uri="inmemory:///customer.mdl",
        text=('domain customer {\n  owner: "team"\n  entity Customer @ 1 (additive) {\n    id: uuid\n  }\n}\n'),
        version=1,
    )

    result = BrowserCompiler().format_source(source)

    assert result.replacement_text is None
    assert any(diagnostic.severity == "error" for diagnostic in result.diagnostics)


def test_compile_json_schema_is_blocked_by_errors():
    source = BrowserSource(
        uri="inmemory:///customer.mdl",
        text=('domain customer {\n  owner: "team"\n  entity Customer @ 1 (additive) {\n    id: uuid\n  }\n}\n'),
        version=1,
    )

    result = BrowserCompiler().compile_json_schema((source,))

    assert result.artifacts == ()
    assert any(diagnostic.severity == "error" for diagnostic in result.diagnostics)


def test_compile_json_schema_returns_text_artifact():
    result = BrowserCompiler().compile_json_schema(
        (BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=1),)
    )

    assert result.diagnostics == ()
    assert len(result.artifacts) == 1
    assert result.artifacts[0].path == "customer.Customer.v1.json"
    assert result.artifacts[0].media_type == "application/schema+json"
    assert result.artifacts[0].source_refs == ("customer.Customer@1",)
    assert json.loads(result.artifacts[0].content)["title"] == "Customer"


def test_dispatch_opens_workspace_from_json():
    response = json.loads(
        dispatch_browser_request(
            "workspace.open",
            json.dumps(
                {
                    "sources": [
                        {
                            "uri": "inmemory:///customer.mdl",
                            "text": VALID,
                            "version": 1,
                        }
                    ]
                }
            ),
        )
    )

    assert response["ok"] is True
    assert response["result"]["diagnostics"] == []
    assert set(response["result"]["source_hashes"]) == {"inmemory:///customer.mdl"}


def test_dispatch_rejects_unknown_method_without_traceback():
    response = json.loads(dispatch_browser_request("shell.run", "{}"))

    assert response == {
        "ok": False,
        "error": {
            "code": "INVALID_REQUEST",
            "message": "Unsupported browser compiler method: shell.run",
        },
    }


def test_dispatch_rejects_malformed_json_without_echoing_source():
    response = json.loads(dispatch_browser_request("workspace.open", '{"secret":'))

    assert response["ok"] is False
    assert response["error"]["code"] == "INVALID_REQUEST"
    assert "secret" not in response["error"]["message"]
    assert "Traceback" not in response["error"]["message"]


def test_dispatch_requires_an_object_with_exact_source_fields():
    non_object = json.loads(dispatch_browser_request("workspace.open", "[]"))
    extra_field = json.loads(
        dispatch_browser_request(
            "source.format",
            json.dumps(
                {
                    "source": {
                        "uri": "inmemory:///customer.mdl",
                        "text": VALID,
                        "version": 1,
                        "path": "C:/private/customer.mdl",
                    }
                }
            ),
        )
    )

    assert non_object["ok"] is False
    assert extra_field["ok"] is False
    assert "C:/private/customer.mdl" not in json.dumps(extra_field)
