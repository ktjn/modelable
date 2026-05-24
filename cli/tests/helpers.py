from __future__ import annotations

import sys
from pathlib import Path

SCENARIOS = Path(__file__).parents[2] / "samples" / "scenarios"
SERVER_CMD = [sys.executable, "-m", "modelable.lsp"]
