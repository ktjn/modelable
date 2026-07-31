"""Documentation retrieval foundation."""

from modelable.rag.evaluation import EvaluationCase, EvaluationReport, evaluate_retrieval
from modelable.rag.model import DocumentationChunk
from modelable.rag.retriever import DocumentationRetriever, RetrievedChunk

__all__ = [
    "DocumentationChunk",
    "DocumentationRetriever",
    "EvaluationCase",
    "EvaluationReport",
    "RetrievedChunk",
    "evaluate_retrieval",
]
