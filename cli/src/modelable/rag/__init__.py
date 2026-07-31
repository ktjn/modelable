"""Documentation retrieval foundation."""

from modelable.rag.evaluation import (
    EvaluationCase,
    EvaluationFailure,
    EvaluationMetrics,
    EvaluationReport,
    evaluate_retrieval,
)
from modelable.rag.generation import RagAnswer, RagCitation, answer_with_retrieval, build_evidence_prompt
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
    "RetrievedChunk",
    "SearchMode",
    "answer_with_retrieval",
    "build_evidence_prompt",
    "evaluate_retrieval",
]
