"""Slice G3: LSP fixture sharing.

`cli/tests/conformance/language/workspace-valid.json` is already the shared
source of truth for `test_browser_conformance.py`'s `language.*` dispatch
tests (completion, hover, definition, references, prepareRename, rename),
but before this file nothing drove the same fixture through the real
`pygls` subprocess LSP server -- so a change that broke the real protocol
handlers while leaving the in-process dispatch layer untouched (or vice
versa) had no test that would catch it. This file is that second consumer:
same fixture text, same request positions, same expectations, run through
`textDocument/*` requests over real JSON-RPC instead of `dispatch_browser_request`.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from lsprotocol import types

_FIXTURE_PATH = Path(__file__).parent / "conformance" / "language" / "workspace-valid.json"
_FIXTURE = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
_SOURCE_TEXT = _FIXTURE["workspace"]["sources"][0]["text"]

# A real file is required before the `lsp` fixture starts the server (root_uri
# is set at initialize time), and `lsp` is parametrized indirectly with a
# static path the way test_lsp_features.py parametrizes it with samples/scenarios
# directories -- so the fixture's text is materialized once, at import time,
# into a throwaway directory rather than a per-test tmp_path.
_WORKSPACE_ROOT = Path(tempfile.mkdtemp(prefix="modelable-lsp-conformance-"))
_CUSTOMER_MDL = _WORKSPACE_ROOT / "customer.mdl"
_CUSTOMER_MDL.write_text(_SOURCE_TEXT, encoding="utf-8")


async def _open(client) -> None:
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=_CUSTOMER_MDL.as_uri(),
                language_id="mdl",
                version=1,
                text=_SOURCE_TEXT,
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)


def _position(request: dict) -> types.Position:
    return types.Position(line=request["line"], character=request["character"])


@pytest.mark.parametrize("lsp", [_WORKSPACE_ROOT], indirect=True)
async def test_fixture_completion_matches_browser_dispatch(lsp):
    await _open(lsp)
    request = _FIXTURE["completion"]["request"]

    result = await lsp.text_document_completion_async(
        types.CompletionParams(
            text_document=types.TextDocumentIdentifier(uri=_CUSTOMER_MDL.as_uri()),
            position=_position(request),
        )
    )

    items = result.items if hasattr(result, "items") else (result or [])
    assert [item.label for item in items] == _FIXTURE["completion"]["labels"]


@pytest.mark.parametrize("lsp", [_WORKSPACE_ROOT], indirect=True)
async def test_fixture_hover_matches_browser_dispatch(lsp):
    await _open(lsp)
    request = _FIXTURE["hover"]["request"]

    result = await lsp.text_document_hover_async(
        types.HoverParams(
            text_document=types.TextDocumentIdentifier(uri=_CUSTOMER_MDL.as_uri()),
            position=_position(request),
        )
    )

    assert result is not None
    markdown = result.contents.value if hasattr(result.contents, "value") else str(result.contents)
    assert _FIXTURE["hover"]["markdownContains"] in markdown


@pytest.mark.parametrize("lsp", [_WORKSPACE_ROOT], indirect=True)
async def test_fixture_definition_matches_browser_dispatch(lsp):
    await _open(lsp)
    request = _FIXTURE["definition"]["request"]

    result = await lsp.text_document_definition_async(
        types.DefinitionParams(
            text_document=types.TextDocumentIdentifier(uri=_CUSTOMER_MDL.as_uri()),
            position=_position(request),
        )
    )

    location = result if isinstance(result, types.Location) else (result[0] if result else None)
    assert location is not None
    assert location.uri == _CUSTOMER_MDL.as_uri()
    assert location.range.start.line == _FIXTURE["definition"]["expectLocation"]["line"]


@pytest.mark.parametrize("lsp", [_WORKSPACE_ROOT], indirect=True)
async def test_fixture_references_matches_browser_dispatch(lsp):
    await _open(lsp)
    request = _FIXTURE["references"]["request"]

    result = await lsp.text_document_references_async(
        types.ReferenceParams(
            text_document=types.TextDocumentIdentifier(uri=_CUSTOMER_MDL.as_uri()),
            position=_position(request),
            context=types.ReferenceContext(include_declaration=request.get("includeDeclaration", True)),
        )
    )

    assert result is not None
    assert len(result) >= _FIXTURE["references"]["minCount"]


@pytest.mark.parametrize("lsp", [_WORKSPACE_ROOT], indirect=True)
async def test_fixture_prepare_rename_matches_browser_dispatch(lsp):
    await _open(lsp)
    request = _FIXTURE["prepareRename"]["request"]

    result = await lsp.text_document_prepare_rename_async(
        types.PrepareRenameParams(
            text_document=types.TextDocumentIdentifier(uri=_CUSTOMER_MDL.as_uri()),
            position=_position(request),
        )
    )

    # The real server returns just the identifier Range (see lsp/rename.py);
    # the browser dispatch layer separately renders a placeholder string for
    # the same range. Slicing the source at the returned range is what
    # proves the two surfaces agree on *which* identifier is being renamed.
    assert isinstance(result, types.Range)
    lines = _SOURCE_TEXT.splitlines()
    identifier = lines[result.start.line][result.start.character : result.end.character]
    assert identifier == _FIXTURE["prepareRename"]["expectPlaceholder"]


@pytest.mark.parametrize("lsp", [_WORKSPACE_ROOT], indirect=True)
async def test_fixture_rename_matches_browser_dispatch(lsp):
    await _open(lsp)
    request = _FIXTURE["rename"]["request"]

    result = await lsp.text_document_rename_async(
        types.RenameParams(
            text_document=types.TextDocumentIdentifier(uri=_CUSTOMER_MDL.as_uri()),
            position=_position(request),
            new_name=request["newName"],
        )
    )

    assert result is not None
    edits = result.changes[_CUSTOMER_MDL.as_uri()]
    assert len(edits) >= _FIXTURE["rename"]["minEdits"]
    assert all(edit.new_text == _FIXTURE["rename"]["expectNewText"] for edit in edits)
