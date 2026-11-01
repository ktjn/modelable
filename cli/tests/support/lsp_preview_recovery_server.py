"""Isolated LSP process; deterministic preview-only dependency faults for recovery tests."""

import sqlite3
import sys
import tempfile
from unittest.mock import patch

from modelable.lsp.server import main
from modelable.operations.compilation import CompilationError, CompilationService

tempfile.tempdir = sys.argv[1]
mode = sys.argv[2]
original_preview = CompilationService.preview
calls = 0
fault_calls = {
    "sqlite-once": {1},
    "sqlite-second": {2},
    "sqlite-first-and-third": {1, 3},
    "programming-once": {1},
    "compilation-second": {2},
}.get(mode, set())


def preview_with_fault(self, *args, **kwargs):
    global calls
    calls += 1
    if calls in fault_calls:
        if mode == "compilation-second":
            raise CompilationError("injected rejected replacement")
        kind = sqlite3.ProgrammingError if mode == "programming-once" else sqlite3.OperationalError
        with patch.object(sqlite3, "connect", side_effect=kind("injected preview database failure")):
            return original_preview(self, *args, **kwargs)
    return original_preview(self, *args, **kwargs)


CompilationService.preview = preview_with_fault
main()
