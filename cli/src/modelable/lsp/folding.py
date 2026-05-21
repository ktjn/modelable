from __future__ import annotations

from lsprotocol import types

from modelable.lsp.workspace import LspWorkspaceIndex


def build_folding_ranges(index: LspWorkspaceIndex, uri: str) -> list[types.FoldingRange] | None:
    source = index.documents.get(uri)
    if source is None:
        return None
    return _compute_folding_ranges(source.text)


def _compute_folding_ranges(text: str) -> list[types.FoldingRange]:
    ranges: list[types.FoldingRange] = []
    lines = text.splitlines()
    stack: list[int] = []
    for line_no, line in enumerate(lines):
        for ch in line:
            if ch == "{":
                stack.append(line_no)
            elif ch == "}" and stack:
                start = stack.pop()
                if start != line_no:
                    ranges.append(
                        types.FoldingRange(
                            start_line=start,
                            end_line=line_no,
                            kind=types.FoldingRangeKind.Region,
                        )
                    )
    return ranges
