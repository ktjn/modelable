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


# ---------------------------------------------------------------------------
# Definition — cross-domain qualified ref in same workspace
# 04/ml-credit-risk.mdl line 19, char 15 → lending.LoanApplication
# Expected: a location in lending.mdl
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [_SCENARIO_04], indirect=True)
async def test_definition_cross_domain_qualified_ref(lsp):
    await _open_file(lsp, _ML_CREDIT_RISK)
    result = await _definition(lsp, _ML_CREDIT_RISK, line=19, char=15)
    assert result is not None, "Expected a definition location, got None"
    uri, _line = result
    assert "lending.mdl" in uri, f"Expected definition in lending.mdl, got: {uri}"


# ---------------------------------------------------------------------------
# Definition — cross-file ref resolves to sibling file
# 03/shipping.mdl line 18, char 20 → payments.PaymentAuthorisation
# Expected: a location in payments.mdl
# ---------------------------------------------------------------------------

_SCENARIO_03 = SCENARIOS / "03-order-saga-microservices"
_SHIPPING_MDL = _SCENARIO_03 / "shipping.mdl"


@pytest.mark.parametrize("lsp", [_SCENARIO_03], indirect=True)
async def test_definition_cross_file_ref(lsp):
    await _open_file(lsp, _SHIPPING_MDL)
    result = await _definition(lsp, _SHIPPING_MDL, line=18, char=20)
    assert result is not None, "Expected a definition location, got None"
    uri, _line = result
    assert "payments.mdl" in uri, f"Expected definition in payments.mdl, got: {uri}"


# ---------------------------------------------------------------------------
# Definition — alias field reference resolves to source model field
# 01/analytics.mdl line 12, char 35 → cust.customerId → Customer.customerId in customer.mdl
# Expected: a location in customer.mdl
# ---------------------------------------------------------------------------

_ANALYTICS_MDL = _SCENARIO_01 / "analytics.mdl"


@pytest.mark.parametrize("lsp", [_SCENARIO_01], indirect=True)
async def test_definition_alias_field_resolves_to_source_model(lsp):
    await _open_file(lsp, _ANALYTICS_MDL)
    result = await _definition(lsp, _ANALYTICS_MDL, line=11, char=35)
    assert result is not None, "Expected a definition location, got None"
    uri, line = result
    assert "customer.mdl" in uri, f"Expected definition in customer.mdl, got: {uri}"


# ---------------------------------------------------------------------------
# References — entity declaration name finds usages across workspace
# 01/customer.mdl line 5, char 12 → Customer entity name
# Expected: at least one reference in analytics.mdl
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [_SCENARIO_01], indirect=True)
async def test_references_entity_name_finds_usages(lsp):
    await _open_file(lsp, _CUSTOMER_MDL)
    locs = await _references(lsp, _CUSTOMER_MDL, line=5, char=12, include_declaration=True)
    assert len(locs) >= 2, f"Expected ≥2 locations (declaration + usages), got {len(locs)}: {locs}"
    uris = [uri for uri, _ in locs]
    assert any("customer.mdl" in u for u in uris), "Expected declaration in customer.mdl"
    assert any("analytics.mdl" in u for u in uris), "Expected usage in analytics.mdl"


# ---------------------------------------------------------------------------
# References — qualified ref returns declaration + all usages
# 01/analytics.mdl line 6, char 20 → customer.Customer @ 3
# Expected: declaration in customer.mdl + at least two references in analytics.mdl
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [_SCENARIO_01], indirect=True)
async def test_references_qualified_ref_returns_declaration_and_usages(lsp):
    await _open_file(lsp, _ANALYTICS_MDL)
    locs = await _references(lsp, _ANALYTICS_MDL, line=6, char=20, include_declaration=True)
    assert len(locs) >= 2, f"Expected ≥2 locations, got {len(locs)}: {locs}"
    uris = [uri for uri, _ in locs]
    assert any("customer.mdl" in u for u in uris), "Expected declaration in customer.mdl"
    assert any("analytics.mdl" in u for u in uris), "Expected reference in analytics.mdl"


# ---------------------------------------------------------------------------
# Completion — reference context after partial domain prefix
# 05/marketplace-api.mdl line 39, char 12 → before_cursor "    from inv"
# prefix "inv" → workspace model refs filtered: includes inventory.SellerInventoryLevel
# ---------------------------------------------------------------------------

_SCENARIO_05 = SCENARIOS / "05-partner-marketplace-api"
_MARKETPLACE_MDL = _SCENARIO_05 / "marketplace-api.mdl"


@pytest.mark.parametrize("lsp", [_SCENARIO_05], indirect=True)
async def test_completion_reference_prefix_filters_candidates(lsp):
    await _open_file(lsp, _MARKETPLACE_MDL)
    labels = await _completion_labels(lsp, _MARKETPLACE_MDL, line=39, char=12)
    assert labels, "Expected completion items, got empty list"
    assert "inventory.SellerInventoryLevel" in labels, (
        f"Expected 'inventory.SellerInventoryLevel' in completions. Got: {labels}"
    )


# ---------------------------------------------------------------------------
# Completion — field candidates inside projection body
# 01/analytics.mdl line 21, char 9 → before_cursor "    total"
# scope is analytics.CustomerLifetimeValue@2 → fields starting with "total"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [_SCENARIO_01], indirect=True)
async def test_completion_field_candidates_inside_projection(lsp):
    await _open_file(lsp, _ANALYTICS_MDL)
    labels = await _completion_labels(lsp, _ANALYTICS_MDL, line=20, char=9)
    assert labels, "Expected field completion items, got empty list"
    assert "totalOrderCount" in labels, (
        f"Expected 'totalOrderCount' in field completions. Got: {labels}"
    )
