import json

import pytest

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import (
    BrowserCompiler,
    BrowserSource,
    dispatch_browser_request,
)

VALID = 'domain customer {\n  owner: "team"\n  entity Customer @ 1 (additive) {\n    @key id: uuid\n  }\n}\n'
URI = "file:///customer.mdl"
SOURCE_TEXT = (
    "domain customer {\n"
    '  owner: "team"\n'
    "  entity Customer @ 1 (additive) {\n"
    "    @key customer_id: uuid\n"
    "    customer_name: string\n"
    "  }\n"
    "}\n"
)
SOURCES = [{"uri": URI, "text": SOURCE_TEXT, "version": 1}]


@pytest.fixture(autouse=True)
def reset_browser_dispatch() -> None:
    browser_dispatch._reset_compiler_for_tests()


def dispatch(method: str, payload: object) -> dict:
    return json.loads(dispatch_browser_request(method, json.dumps(payload)))


def test_open_workspace_returns_hashes_and_no_diagnostics():
    result = BrowserCompiler().open_workspace(
        1,
        (BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=1),),
    )

    assert result.workspace_revision == 1
    assert result.diagnostics == ()
    assert set(result.source_hashes) == {"inmemory:///customer.mdl"}
    assert len(result.source_hashes["inmemory:///customer.mdl"]) == 64


def test_open_workspace_source_hashes_are_deeply_immutable():
    result = BrowserCompiler().open_workspace(
        1,
        (BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=1),),
    )

    with pytest.raises(TypeError):
        result.source_hashes["inmemory:///customer.mdl"] = "mutated"


def test_open_workspace_rejects_duplicate_uris():
    source = BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=1)

    with pytest.raises(ValueError, match="Source URIs must be unique"):
        BrowserCompiler().open_workspace(1, (source, source))


def test_open_workspace_rejects_non_positive_versions():
    source = BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=0)

    with pytest.raises(
        ValueError,
        match=r"Source versions must be positive: inmemory:///customer\.mdl",
    ):
        BrowserCompiler().open_workspace(1, (source,))


def test_open_workspace_returns_parse_error_for_the_source():
    source = BrowserSource(
        uri="inmemory:///broken.mdl",
        text="domain customer {",
        version=1,
    )

    result = BrowserCompiler().open_workspace(1, (source,))

    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "PARSE"
    assert result.diagnostics[0].severity == "error"
    assert result.diagnostics[0].uri == "inmemory:///broken.mdl"
    assert result.diagnostics[0].line is not None
    assert set(result.source_hashes) == {"inmemory:///broken.mdl"}


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

    result = BrowserCompiler().open_workspace(1, (first, second))

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


def test_compile_json_schema_blocks_duplicate_definitions_across_uris():
    sources = (
        BrowserSource(uri="inmemory:///customer-a.mdl", text=VALID, version=1),
        BrowserSource(uri="inmemory:///customer-b.mdl", text=VALID, version=1),
    )

    result = BrowserCompiler().compile_json_schema(sources)

    assert result.artifacts == ()
    assert any(diagnostic.message.startswith("duplicate domain 'customer'") for diagnostic in result.diagnostics)
    assert any(
        diagnostic.message.startswith("duplicate model version customer.Customer@1")
        for diagnostic in result.diagnostics
    )


def test_dispatch_opens_workspace_from_json():
    response = json.loads(
        dispatch_browser_request(
            "workspace.open",
            json.dumps(
                {
                    "workspaceRevision": 1,
                    "sources": [
                        {
                            "uri": "inmemory:///customer.mdl",
                            "text": VALID,
                            "version": 1,
                        }
                    ],
                }
            ),
        )
    )

    assert response["ok"] is True
    assert response["result"]["diagnostics"] == []
    assert response["result"]["workspace_revision"] == 1
    assert set(response["result"]["source_hashes"]) == {"inmemory:///customer.mdl"}
    assert isinstance(response["result"]["source_hashes"], dict)


def test_dispatch_rejects_unknown_method_without_traceback():
    response = json.loads(dispatch_browser_request("shell.run", "{}"))

    assert response == {
        "ok": False,
        "error": {
            "code": "INVALID_REQUEST",
            "message": "Payload does not match method schema",
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


@pytest.mark.parametrize("exception_type", [ValueError, TypeError])
def test_dispatch_propagates_unexpected_compiler_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    exception_type: type[Exception],
) -> None:
    secret = "C:/private/checkout/customer.mdl TOP SECRET SOURCE"

    def fail_operation(
        _self: BrowserCompiler,
        _workspace_revision: int,
        _sources: tuple[BrowserSource, ...],
    ) -> None:
        raise exception_type(secret)

    monkeypatch.setattr(BrowserCompiler, "open_workspace", fail_operation)

    with pytest.raises(exception_type) as raised:
        dispatch_browser_request(
            "workspace.open",
            json.dumps(
                {
                    "workspaceRevision": 1,
                    "sources": [
                        {
                            "uri": "inmemory:///customer.mdl",
                            "text": VALID,
                            "version": 1,
                        }
                    ],
                }
            ),
        )

    assert secret in str(raised.value)


def test_dispatch_classifies_dto_construction_errors_as_invalid_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "C:/private/checkout/customer.mdl TOP SECRET SOURCE"
    assert hasattr(browser_dispatch, "BrowserRequestValidationError")

    def reject_dto(**_values: object) -> BrowserSource:
        raise browser_dispatch.BrowserRequestValidationError(secret)

    monkeypatch.setattr(browser_dispatch, "BrowserSource", reject_dto)

    response = json.loads(
        dispatch_browser_request(
            "source.format",
            json.dumps(
                {
                    "source": {
                        "uri": "inmemory:///customer.mdl",
                        "text": VALID,
                        "version": 1,
                    }
                }
            ),
        )
    )

    assert response["error"] == {
        "code": "INVALID_REQUEST",
        "message": "Payload does not match method schema",
    }
    assert secret not in json.dumps(response)


def test_dispatch_syncs_revision_then_completes() -> None:
    opened = dispatch("workspace.open", {"workspaceRevision": 7, "sources": SOURCES})
    result = dispatch(
        "language.completion",
        {"workspaceRevision": 7, "uri": URI, "line": 4, "character": 4},
    )

    assert opened["result"]["workspace_revision"] == 7
    assert result["result"]["items"][0]["label"] == "customer_id"
    assert result["result"]["items"][0]["replacement"] == {
        "end": {"character": 4, "line": 4},
        "start": {"character": 4, "line": 4},
    }


def test_dispatch_hovers_from_synchronized_workspace() -> None:
    dispatch("workspace.open", {"workspaceRevision": 7, "sources": SOURCES})

    result = dispatch(
        "language.hover",
        {"workspaceRevision": 7, "uri": URI, "line": 3, "character": 10},
    )

    assert result["ok"] is True
    assert "customer_id" in result["result"]["hover"]["markdown"]


def test_language_request_rejects_stale_revision_without_source_echo() -> None:
    dispatch("workspace.open", {"workspaceRevision": 7, "sources": SOURCES})

    result = dispatch(
        "language.hover",
        {"workspaceRevision": 6, "uri": URI, "line": 1, "character": 2},
    )

    assert result["error"] == {
        "code": "STALE_WORKSPACE",
        "message": "Requested workspace revision is not current",
    }
    serialized = json.dumps(result)
    assert SOURCE_TEXT not in serialized
    assert "customer" not in serialized


def test_workspace_open_rejects_stale_revision_without_replacing_state() -> None:
    dispatch("workspace.open", {"workspaceRevision": 7, "sources": SOURCES})

    stale = dispatch("workspace.open", {"workspaceRevision": 6, "sources": SOURCES})
    current = dispatch(
        "language.completion",
        {"workspaceRevision": 7, "uri": URI, "line": 4, "character": 4},
    )

    assert stale["error"]["code"] == "STALE_WORKSPACE"
    assert current["result"]["items"][0]["label"] == "customer_id"


@pytest.mark.parametrize(
    "method,payload",
    [
        (
            "workspace.open",
            {"sources": SOURCES},
        ),
        (
            "workspace.open",
            {"workspaceRevision": 1, "sources": SOURCES, "extra": "secret"},
        ),
        (
            "workspace.open",
            {"workspaceRevision": True, "sources": SOURCES},
        ),
        (
            "language.completion",
            {"workspaceRevision": 1, "uri": URI, "line": 0},
        ),
        (
            "language.completion",
            {
                "workspaceRevision": 1,
                "uri": URI,
                "line": 0,
                "character": 0,
                "extra": "secret",
            },
        ),
        (
            "language.hover",
            {"workspaceRevision": 1, "uri": URI, "line": False, "character": 0},
        ),
    ],
)
def test_protocol_v2_payloads_require_exact_fields_and_non_boolean_integers(
    method: str,
    payload: dict,
) -> None:
    result = dispatch(method, payload)

    assert result["error"] == {
        "code": "INVALID_REQUEST",
        "message": "Payload does not match method schema",
    }
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    ("uri", "line", "character"),
    [
        ("file:///missing.mdl", 0, 0),
        (URI, -1, 0),
        (URI, 99, 0),
        (URI, 0, -1),
        (URI, 0, 99),
        (URI, 0, 8),
    ],
)
def test_language_request_rejects_invalid_uri_or_utf16_position(
    uri: str,
    line: int,
    character: int,
) -> None:
    astral_sources = [
        {
            "uri": URI,
            "text": SOURCE_TEXT.replace("domain customer", "domain 😀customer"),
            "version": 1,
        }
    ]
    dispatch("workspace.open", {"workspaceRevision": 1, "sources": astral_sources})

    result = dispatch(
        "language.completion",
        {
            "workspaceRevision": 1,
            "uri": uri,
            "line": line,
            "character": character,
        },
    )

    assert result["error"] == {
        "code": "INVALID_POSITION",
        "message": "Requested language position is invalid",
    }
    assert SOURCE_TEXT not in json.dumps(result)


def test_language_request_reports_unavailable_only_after_valid_position() -> None:
    invalid = [{"uri": URI, "text": "domain broken {", "version": 1}]
    dispatch("workspace.open", {"workspaceRevision": 1, "sources": invalid})

    valid_position = dispatch(
        "language.hover",
        {"workspaceRevision": 1, "uri": URI, "line": 0, "character": 0},
    )
    invalid_position = dispatch(
        "language.hover",
        {"workspaceRevision": 1, "uri": "file:///missing.mdl", "line": 0, "character": 0},
    )

    assert valid_position["error"]["code"] == "LANGUAGE_UNAVAILABLE"
    assert invalid_position["error"]["code"] == "INVALID_POSITION"
    assert "broken" not in json.dumps(valid_position)


def test_completion_and_hover_use_current_text_with_last_parseable_semantics() -> None:
    dispatch("workspace.open", {"workspaceRevision": 1, "sources": SOURCES})
    invalid_text = SOURCE_TEXT.replace("    customer_name: string", "    customer_na").rstrip("}\n")
    invalid_sources = [{"uri": URI, "text": invalid_text, "version": 2}]
    opened = dispatch("workspace.open", {"workspaceRevision": 2, "sources": invalid_sources})
    line = invalid_text.splitlines().index("    customer_na")

    completion = dispatch(
        "language.completion",
        {"workspaceRevision": 2, "uri": URI, "line": line, "character": 15},
    )
    hover = dispatch(
        "language.hover",
        {"workspaceRevision": 2, "uri": URI, "line": 3, "character": 10},
    )

    assert opened["result"]["workspace_revision"] == 2
    assert opened["result"]["diagnostics"][0]["code"] == "PARSE"
    assert [item["label"] for item in completion["result"]["items"]] == ["customer_name"]
    assert "customer_id" in hover["result"]["hover"]["markdown"]


def test_language_results_serialize_deterministically_and_without_catalog_candidates() -> None:
    dispatch("workspace.open", {"workspaceRevision": 1, "sources": SOURCES})
    request = json.dumps({"workspaceRevision": 1, "uri": URI, "line": 0, "character": 0})

    first = dispatch_browser_request("language.completion", request)
    second = dispatch_browser_request("language.completion", request)

    assert first == second
    assert '"remote"' not in first
    assert first == json.dumps(json.loads(first), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_language_error_messages_do_not_include_source_symbol_or_result_text() -> None:
    secret_symbol = "secret_customer_symbol"
    secret_result = "secret completion result"
    sources = [
        {
            "uri": URI,
            "text": SOURCE_TEXT.replace("customer_id", secret_symbol),
            "version": 1,
        }
    ]
    dispatch("workspace.open", {"workspaceRevision": 8, "sources": sources})

    result = dispatch(
        "language.hover",
        {
            "workspaceRevision": 7,
            "uri": URI,
            "line": 3,
            "character": len(secret_result),
        },
    )

    serialized = json.dumps(result)
    assert SOURCE_TEXT not in serialized
    assert secret_symbol not in serialized
    assert secret_result not in serialized
