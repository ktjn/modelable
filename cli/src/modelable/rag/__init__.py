"""Documentation retrieval foundation."""

from modelable.rag.evaluation import (
    EvaluationCase,
    EvaluationFailure,
    EvaluationMetrics,
    EvaluationReport,
    evaluate_retrieval,
)
from modelable.rag.model import DocumentationChunk
from modelable.rag.retriever import DocumentationRetriever, RetrievedChunk

__all__ = [
    "DocumentationChunk",
    "DocumentationRetriever",
    "EvaluationCase",
    "EvaluationFailure",
    "EvaluationMetrics",
    "EvaluationReport",
    "RetrievedChunk",
    "evaluate_retrieval",
]
