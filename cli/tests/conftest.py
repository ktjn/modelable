from pathlib import Path
import os
import tempfile

import pytest


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
