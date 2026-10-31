"""Isolated real LSP process with test-only staging location/fault injection."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import modelable.operations.compilation as compilation
from modelable.lsp.server import main

tempfile.tempdir = sys.argv[1]
if sys.argv[2] == "cleanup":
    original_apply = compilation.CompilationService.apply

    def fail_cleanup(path: Path) -> None:
        raise compilation.CompilationError(f"injected staging cleanup failure: {path}")

    def apply_with_cleanup_fault(self, pending, *, confirmation):
        with patch.object(compilation, "_remove_staging", fail_cleanup):
            return original_apply(self, pending, confirmation=confirmation)

    compilation.CompilationService.apply = apply_with_cleanup_fault

main()
