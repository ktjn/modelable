import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from helpers import SERVER_CMD
from lsprotocol import types
from pytest_lsp.client import make_test_lsp_client

import modelable._pydantic_py314_compat  # noqa: F401 — must precede pydantic model imports

FIXTURES = Path(__file__).parent / "fixtures"
LOCAL_TMP = Path(__file__).resolve().parents[1] / ".pytest_tmp"
LOCAL_TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMP", str(LOCAL_TMP))
os.environ.setdefault("TEMP", str(LOCAL_TMP))
os.environ.setdefault("TMPDIR", str(LOCAL_TMP))
tempfile.tempdir = str(LOCAL_TMP)


@pytest.fixture
def fixture_path():
    return FIXTURES


@pytest_asyncio.fixture
async def lsp(request):
    """Start the LSP server and complete the initialize handshake.

    The ``workspace_root`` parameter (a Path) is passed via indirect fixture
    parametrization or the ``lsp_workspace`` pytest mark.
    """
    workspace_root: Path = request.param
    client = make_test_lsp_client()
    await client.start_io(*SERVER_CMD)
    await client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=workspace_root.as_uri(),
            workspace_folders=[
                types.WorkspaceFolder(uri=workspace_root.as_uri(), name=workspace_root.name)
            ],
        )
    )
    yield client
    await client.shutdown_session()
