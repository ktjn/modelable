"""
End-to-end integration tests for the Modelable LSP server.

These tests start the server as a real subprocess, drive it through the full
LSP protocol using pytest-lsp, and assert on published diagnostics — covering
the initialization flow that unit tests cannot reach (workspace scanning,
cross-file reference resolution, etc.).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from helpers import SCENARIOS, SERVER_CMD
from lsprotocol import types
from pytest_lsp.client import make_test_lsp_client

SAMPLES = SCENARIOS.parent


async def _open_and_get_diagnostics(
    client, path: Path
) -> list[types.Diagnostic]:
    """Open a document and wait for the server to publish diagnostics for it."""
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
    return list(client.diagnostics.get(path.as_uri(), []))


# ---------------------------------------------------------------------------
# Scenario 04: credit-risk-feature-store
# Cross-file refs: lending.LoanApplication, customer.CustomerFinancials,
#                  credit-bureau.BureauReport
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [SCENARIOS / "04-credit-risk-feature-store"], indirect=True)
async def test_cross_domain_refs_resolve_in_credit_risk(lsp):
    ml_file = SCENARIOS / "04-credit-risk-feature-store" / "ml-credit-risk.mdl"
    diags = await _open_and_get_diagnostics(lsp, ml_file)
    unresolved = [d for d in diags if "unresolved model reference" in d.message]
    assert unresolved == [], f"Unresolved references: {[d.message for d in unresolved]}"


# ---------------------------------------------------------------------------
# Scenario 05: partner-marketplace-api
# Cross-file ref: inventory.SellerInventoryLevel in marketplace-api.mdl
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [SCENARIOS / "05-partner-marketplace-api"], indirect=True)
async def test_cross_domain_refs_resolve_in_marketplace_api(lsp):
    mp_file = SCENARIOS / "05-partner-marketplace-api" / "marketplace-api.mdl"
    diags = await _open_and_get_diagnostics(lsp, mp_file)
    unresolved = [d for d in diags if "unresolved model reference" in d.message]
    assert unresolved == [], f"Unresolved references: {[d.message for d in unresolved]}"


# ---------------------------------------------------------------------------
# Scenario 03: order-saga-microservices
# Cross-file ref: payments.PaymentAuthorisation in shipping.mdl
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [SCENARIOS / "03-order-saga-microservices"], indirect=True)
async def test_cross_domain_refs_resolve_in_shipping(lsp):
    ship_file = SCENARIOS / "03-order-saga-microservices" / "shipping.mdl"
    diags = await _open_and_get_diagnostics(lsp, ship_file)
    unresolved = [d for d in diags if "unresolved model reference" in d.message]
    assert unresolved == [], f"Unresolved references: {[d.message for d in unresolved]}"


# ---------------------------------------------------------------------------
# Single-file fallback: open a file WITHOUT workspace folders configured.
# The server should still scan the parent directory and resolve siblings.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def lsp_no_folder():
    """Start the LSP server without any workspace folder (rootless session)."""
    client = make_test_lsp_client()
    await client.start_io(*SERVER_CMD)
    await client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
        )
    )
    yield client
    await client.shutdown_session()


async def test_cross_domain_refs_resolve_without_workspace_folder(lsp_no_folder):
    """When no workspace folder is configured, opening a file triggers a sibling
    directory scan that should resolve cross-file references."""
    mp_file = SCENARIOS / "05-partner-marketplace-api" / "marketplace-api.mdl"
    diags = await _open_and_get_diagnostics(lsp_no_folder, mp_file)
    unresolved = [d for d in diags if "unresolved model reference" in d.message]
    assert unresolved == [], f"Unresolved references: {[d.message for d in unresolved]}"


# ---------------------------------------------------------------------------
# Project-root workspace: workspace folder is the SCENARIOS parent directory.
# The server must NOT load all scenarios (they share domain names), and instead
# walk up from the opened file to find the nearest workspace.mdl boundary.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def lsp_project_root():
    """Start the LSP server with workspace root = the scenarios directory."""
    client = make_test_lsp_client()
    await client.start_io(*SERVER_CMD)
    await client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=SCENARIOS.as_uri(),
            workspace_folders=[
                types.WorkspaceFolder(uri=SCENARIOS.as_uri(), name=SCENARIOS.name)
            ],
        )
    )
    yield client
    await client.shutdown_session()


async def test_cross_domain_refs_resolve_with_project_root_workspace(lsp_project_root):
    """When workspace root is a parent directory (no workspace.mdl there), opening a
    file should walk up to the nearest workspace.mdl and scan only that scope."""
    mp_file = SCENARIOS / "05-partner-marketplace-api" / "marketplace-api.mdl"
    diags = await _open_and_get_diagnostics(lsp_project_root, mp_file)
    unresolved = [d for d in diags if "unresolved model reference" in d.message]
    assert unresolved == [], f"Unresolved references: {[d.message for d in unresolved]}"


# ---------------------------------------------------------------------------
# MVP sample (no workspace.mdl): cross-file refs in a plain directory.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lsp", [SAMPLES / "mvp"], indirect=True)
async def test_cross_domain_refs_resolve_in_mvp_without_workspace_file(lsp):
    """When a workspace folder has multiple .mdl files but no workspace.mdl,
    opening one file should still resolve sibling model references."""
    billing_file = SAMPLES / "mvp" / "billing.mdl"
    diags = await _open_and_get_diagnostics(lsp, billing_file)
    unresolved = [d for d in diags if "unresolved model reference" in d.message]
    unknown_alias = [d for d in diags if "unknown alias 'c'" in d.message]
    assert unresolved == [], f"Unresolved references: {[d.message for d in unresolved]}"
    assert unknown_alias == [], f"Alias errors: {[d.message for d in unknown_alias]}"
