from __future__ import annotations

import pytest
from lsprotocol import types
from pathlib import Path

from helpers import SCENARIOS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _open_file(client, path: Path) -> None:
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=path.as_uri(),
                language_id="mdl",
                version=1,
                text=path.read_text(encoding="utf-8"),
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)


async def _hover(client, path: Path, line: int, char: int) -> str | None:
    result = await client.protocol.send_request_async(
        types.TEXT_DOCUMENT_HOVER,
        types.HoverParams(
            text_document=types.TextDocumentIdentifier(uri=path.as_uri()),
            position=types.Position(line=line, character=char),
        ),
    )
    if result is None:
        return None
    contents = result.contents
    return contents.value if hasattr(contents, "value") else str(contents)


async def _definition(client, path: Path, line: int, char: int) -> tuple[str, int] | None:
    result = await client.protocol.send_request_async(
        types.TEXT_DOCUMENT_DEFINITION,
        types.DefinitionParams(
            text_document=types.TextDocumentIdentifier(uri=path.as_uri()),
            position=types.Position(line=line, character=char),
        ),
    )
    if result is None:
        return None
    location = result if isinstance(result, types.Location) else (result[0] if result else None)
    if location is None:
        return None
    return location.uri, location.range.start.line


async def _references(
    client, path: Path, line: int, char: int, include_declaration: bool = True
) -> list[tuple[str, int]]:
    result = await client.protocol.send_request_async(
        types.TEXT_DOCUMENT_REFERENCES,
        types.ReferenceParams(
            text_document=types.TextDocumentIdentifier(uri=path.as_uri()),
            position=types.Position(line=line, character=char),
            context=types.ReferenceContext(include_declaration=include_declaration),
        ),
    )
    if not result:
        return []
    return [(loc.uri, loc.range.start.line) for loc in result]


async def _completion_labels(client, path: Path, line: int, char: int) -> list[str]:
    result = await client.protocol.send_request_async(
        types.TEXT_DOCUMENT_COMPLETION,
        types.CompletionParams(
            text_document=types.TextDocumentIdentifier(uri=path.as_uri()),
            position=types.Position(line=line, character=char),
        ),
    )
    if result is None:
        return []
    items = result.items if hasattr(result, "items") else result
    return [item.label for item in items]


# ---------------------------------------------------------------------------
# Hover — qualified cross-domain type reference
# ml-credit-risk.mdl line 19: `    join lending.LoanApplication @ 1 as app ...`
# char 15 is inside `lending` of `lending.LoanApplication @ 1`
# ---------------------------------------------------------------------------

_SCENARIO_04 = SCENARIOS / "04-credit-risk-feature-store"
_ML_CREDIT_RISK = _SCENARIO_04 / "ml-credit-risk.mdl"


@pytest.mark.parametrize("lsp", [_SCENARIO_04], indirect=True)
async def test_hover_qualified_cross_domain_ref(lsp):
    await _open_file(lsp, _ML_CREDIT_RISK)
    text = await _hover(lsp, _ML_CREDIT_RISK, line=19, char=15)
    assert text is not None, "Expected hover result, got None"
    assert "LoanApplication" in text, f"Expected 'LoanApplication' in hover, got:\n{text}"


# ---------------------------------------------------------------------------
# Hover — bare field name inside projection body
# ml-credit-risk.mdl line 27: `    applicationId          <- lbl.applicationId`
# char 8 is inside `applicationId` (the projection output field name)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [_SCENARIO_04], indirect=True)
async def test_hover_projection_field_name(lsp):
    await _open_file(lsp, _ML_CREDIT_RISK)
    text = await _hover(lsp, _ML_CREDIT_RISK, line=27, char=8)
    assert text is not None, "Expected hover result for projection field, got None"
    assert "applicationId" in text, f"Expected field name in hover, got:\n{text}"


# ---------------------------------------------------------------------------
# Hover — alias.field reference resolves through join alias
# ml-credit-risk.mdl line 42: `    bureau_credit_score    <- bur.creditScore`
# char 35 is inside `creditScore` of `bur.creditScore`
# bur is aliased to credit-bureau.BureauReport @ 1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [_SCENARIO_04], indirect=True)
async def test_hover_alias_field_resolves_through_join(lsp):
    await _open_file(lsp, _ML_CREDIT_RISK)
    text = await _hover(lsp, _ML_CREDIT_RISK, line=42, char=35)
    assert text is not None, "Expected hover result for alias field, got None"
    assert "creditScore" in text, f"Expected field info in hover, got:\n{text}"


# ---------------------------------------------------------------------------
# Hover — entity declaration name shows model summary
# 01-ecommerce customer.mdl line 5: `  entity Customer @ 3 (additive) {`
# char 12 is inside `Customer`
# ---------------------------------------------------------------------------

_SCENARIO_01 = SCENARIOS / "01-ecommerce-data-warehouse"
_CUSTOMER_MDL = _SCENARIO_01 / "customer.mdl"


@pytest.mark.parametrize("lsp", [_SCENARIO_01], indirect=True)
async def test_hover_entity_declaration_name(lsp):
    await _open_file(lsp, _CUSTOMER_MDL)
    text = await _hover(lsp, _CUSTOMER_MDL, line=5, char=12)
    assert text is not None, "Expected hover result for entity name, got None"
    assert "Customer" in text, f"Expected entity name in hover, got:\n{text}"
