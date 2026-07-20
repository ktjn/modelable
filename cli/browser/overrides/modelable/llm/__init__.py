"""Browser-safe exports for local language-service summaries."""

from modelable.llm.context import (
    build_model_summary,
    build_projection_summary,
    build_workspace_summary,
    parse_model_ref,
    parse_model_ref_version_spec,
)

__all__ = [
    "build_model_summary",
    "build_projection_summary",
    "build_workspace_summary",
    "parse_model_ref",
    "parse_model_ref_version_spec",
]
