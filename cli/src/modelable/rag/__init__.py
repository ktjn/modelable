"""Documentation retrieval foundation."""

from importlib import import_module
from typing import Any

from modelable.rag.context import select_context
from modelable.rag.evaluation import (
    EvaluationCase,
    EvaluationFailure,
    EvaluationMetrics,
    EvaluationReport,
    evaluate_retrieval,
    evaluate_retrieval_modes,
)
from modelable.rag.intent import RetrievalDecision, RetrievalRoute, classify_retrieval_intent
from modelable.rag.model import DocumentationChunk
from modelable.rag.retriever import DocumentationRetriever, RetrievedChunk, SearchMode

__all__ = [
    "DocumentationChunk",
    "DocumentationRetriever",
    "EvaluationCase",
    "EvaluationFailure",
    "EvaluationMetrics",
    "EvaluationReport",
    "RagAnswer",
    "RagCitation",
    "RetrievalDecision",
    "RetrievalRoute",
    "RetrievedChunk",
    "SearchMode",
    "answer_with_retrieval",
    "build_evidence_prompt",
    "classify_retrieval_intent",
    "evaluate_retrieval",
    "evaluate_retrieval_modes",
    "select_context",
]


def __getattr__(name: str) -> Any:
    if name in {"RagAnswer", "RagCitation", "answer_with_retrieval", "build_evidence_prompt"}:
        module = import_module("modelable.rag.generation")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
