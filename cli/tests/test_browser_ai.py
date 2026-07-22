import json

import pytest

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import (
    BrowserCompiler,
    BrowserSource,
    dispatch_browser_request,
)
from modelable.browser.ai import (
    build_explain_request,
    build_generate_entity_request,
    parse_explain_result,
    parse_generate_result,
)
from modelable.browser.dto import BrowserAiPendingResult

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


@pytest.fixture(autouse=True)
def reset_browser_dispatch() -> None:
    browser_dispatch._reset_compiler_for_tests()


def dispatch(method: str, payload: object) -> dict:
    return json.loads(dispatch_browser_request(method, json.dumps(payload)))


def _open_workspace(compiler: BrowserCompiler) -> int:
    result = compiler.open_workspace(
        1,
        (BrowserSource(uri=URI, text=SOURCE_TEXT, version=1),),
    )
    return result.workspace_revision


def test_build_generate_entity_request_returns_pending():
    compiler = BrowserCompiler()
    _open_workspace(compiler)

    result = build_generate_entity_request(
        compiler.language,
        description="A product catalog item",
        domain_name="catalog",
        model_name="Product",
    )

    assert isinstance(result, BrowserAiPendingResult)
    assert result.llm_request.temperature == 0.2
    assert result.llm_request.response_format == "text"
    assert "Product" in result.llm_request.user
    assert "catalog" in result.llm_request.user


def test_build_explain_request_returns_pending():
    compiler = BrowserCompiler()
    _open_workspace(compiler)

    result = build_explain_request(
        compiler.language,
        ref="customer.Customer@1",
        diagnostic_index=None,
    )

    assert isinstance(result, BrowserAiPendingResult)
    assert "customer.Customer@1" in result.llm_request.user


def test_build_explain_request_with_diagnostic_index():
    compiler = BrowserCompiler()
    _open_workspace(compiler)

    result = build_explain_request(
        compiler.language,
        ref=None,
        diagnostic_index=0,
    )

    assert isinstance(result, BrowserAiPendingResult)
    assert "workspace" in result.llm_request.user.lower()


def test_parse_generate_result_valid_source():
    source = (
        "domain catalog {\n"
        '  owner: "team"\n'
        "  entity Product @ 1 (additive) {\n"
        "    @key product_id: uuid\n"
        "    name: string\n"
        "  }\n"
        "}\n"
    )
    result = parse_generate_result(source)
    assert result.source == source
    assert len([d for d in result.diagnostics if d.severity == "error"]) == 0


def test_parse_generate_result_strips_code_fences():
    source = "```mdl\ndomain x { owner: \"t\" entity Y @ 1 (additive) { @key y_id: uuid } }\n```"
    result = parse_generate_result(source)
    assert not result.source.startswith("```")
    assert not result.source.endswith("```")


def test_parse_generate_result_invalid_source():
    result = parse_generate_result("this is not valid mdl")
    assert len(result.diagnostics) > 0
    assert any(d.severity == "error" for d in result.diagnostics)


def test_parse_explain_result():
    result = parse_explain_result("  This model represents a customer.  ")
    assert result.explanation == "This model represents a customer."


def test_dispatch_ai_generate_phase_one():
    result = dispatch("workspace.open", {
        "workspaceRevision": 1,
        "sources": [{"uri": URI, "text": SOURCE_TEXT, "version": 1}],
    })
    assert result["ok"]

    result = dispatch("ai.generate", {
        "workspaceRevision": 1,
        "action": "generate_entity",
        "parameters": {"description": "A product", "domainName": "catalog"},
    })
    assert result["ok"]
    assert result["result"]["status"] == "pending_llm"
    assert "system" in result["result"]["llm_request"]
    assert "user" in result["result"]["llm_request"]


def test_dispatch_ai_generate_phase_two():
    dispatch("workspace.open", {
        "workspaceRevision": 1,
        "sources": [{"uri": URI, "text": SOURCE_TEXT, "version": 1}],
    })

    generated_source = (
        "domain catalog {\n"
        '  owner: "team"\n'
        "  entity Product @ 1 (additive) {\n"
        "    @key product_id: uuid\n"
        "    name: string\n"
        "  }\n"
        "}\n"
    )
    result = dispatch("ai.generate", {
        "workspaceRevision": 1,
        "action": "generate_entity",
        "parameters": {"description": "A product"},
        "llmResponseContent": generated_source,
    })
    assert result["ok"]
    assert "source" in result["result"]
    assert "diagnostics" in result["result"]


def test_dispatch_ai_explain_phase_one():
    dispatch("workspace.open", {
        "workspaceRevision": 1,
        "sources": [{"uri": URI, "text": SOURCE_TEXT, "version": 1}],
    })

    result = dispatch("ai.explain", {
        "workspaceRevision": 1,
        "parameters": {"ref": "customer.Customer@1"},
    })
    assert result["ok"]
    assert result["result"]["status"] == "pending_llm"


def test_dispatch_ai_explain_phase_two():
    dispatch("workspace.open", {
        "workspaceRevision": 1,
        "sources": [{"uri": URI, "text": SOURCE_TEXT, "version": 1}],
    })

    result = dispatch("ai.explain", {
        "workspaceRevision": 1,
        "parameters": {},
        "llmResponseContent": "This workspace defines a customer domain.",
    })
    assert result["ok"]
    assert result["result"]["explanation"] == "This workspace defines a customer domain."


def test_dispatch_ai_generate_invalid_action():
    dispatch("workspace.open", {
        "workspaceRevision": 1,
        "sources": [{"uri": URI, "text": SOURCE_TEXT, "version": 1}],
    })

    result = dispatch("ai.generate", {
        "workspaceRevision": 1,
        "action": "invalid_action",
        "parameters": {},
    })
    assert not result["ok"]
    assert result["error"]["code"] == "INVALID_REQUEST"


def test_dispatch_ai_generate_stale_workspace():
    dispatch("workspace.open", {
        "workspaceRevision": 1,
        "sources": [{"uri": URI, "text": SOURCE_TEXT, "version": 1}],
    })

    result = dispatch("ai.generate", {
        "workspaceRevision": 99,
        "action": "generate_entity",
        "parameters": {},
    })
    assert not result["ok"]
    assert result["error"]["code"] == "STALE_WORKSPACE"
