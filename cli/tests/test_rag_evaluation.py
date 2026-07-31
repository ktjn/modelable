from pathlib import Path

import pytest

from modelable.rag.chunking import load_documentation_chunks
from modelable.rag.evaluation import (
    EvaluationCase,
    evaluate_retrieval,
    load_evaluation_cases,
)
from modelable.rag.retriever import RetrievedChunk


def _chunk(external_id: str, source_path: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        id=1,
        external_id=external_id,
        url=f"https://example.test/{external_id}",
        score=score,
        title="Guide",
        heading="Install",
        content="Install with uv.",
        source_path=source_path,
        heading_path=["Guide", "Install"],
        content_hash="hash",
    )


class FakeRetriever:
    def search(self, query: str, *, limit: int) -> list[RetrievedChunk]:
        assert query == "How do I install?"
        assert limit == 10
        return [
            _chunk("guide.md#other", "guide.md", 10.0),
            _chunk("guide.md#install", "guide.md", 9.0),
            _chunk("config.md#install", "config.md", 8.0),
        ][:limit]


def test_evaluate_retrieval_calculates_baseline_metrics() -> None:
    report = evaluate_retrieval(
        FakeRetriever(),
        [EvaluationCase("How do I install?", ("guide.md#install",))],
    )

    assert report.case_count == 1
    assert report.recall_at_5 == 1.0
    assert report.recall_at_10 == 1.0
    assert report.mean_reciprocal_rank == pytest.approx(0.5)
    assert report.ndcg_at_10 == pytest.approx(1 / 1.5849625007)
    assert report.zero_result_rate == 0.0
    assert report.duplicate_source_rate == pytest.approx(1 / 3)


def test_evaluate_retrieval_reports_zeroes_for_empty_corpus() -> None:
    report = evaluate_retrieval(FakeRetriever(), [])

    assert report.case_count == 0
    assert report.recall_at_5 == 0.0
    assert report.mean_reciprocal_rank == 0.0


def test_evaluate_retrieval_reports_categories_and_failed_queries() -> None:
    class CategorizedRetriever:
        def search(self, query: str, *, limit: int) -> list[RetrievedChunk]:
            if query == "domain ownership":
                return [_chunk("architecture.md#21-domain-ownership", "architecture.md", 4.0)]
            return []

    report = evaluate_retrieval(
        CategorizedRetriever(),
        [
            EvaluationCase("domain ownership", ("architecture.md#21-domain-ownership",), "lexical"),
            EvaluationCase("who owns domains?", ("architecture.md#21-domain-ownership",), "challenge"),
        ],
    )

    assert [summary.category for summary in report.category_reports] == ["challenge", "lexical"]
    assert report.category_reports[1].recall_at_10 == 1.0
    assert report.category_reports[0].zero_result_rate == 1.0
    assert report.failures[0].question == "who owns domains?"
    assert report.failures[0].returned_chunk_ids == ()


def test_load_evaluation_cases_validates_yaml_shape(tmp_path: Path) -> None:
    corpus = tmp_path / "evaluation.yaml"
    corpus.write_text(
        "cases:\n  - category: lexical\n    question: How do I install?\n    relevant_chunks:\n      - guide.md#install\n",
        encoding="utf-8",
    )

    assert load_evaluation_cases(corpus) == [EvaluationCase("How do I install?", ("guide.md#install",), "lexical")]


def test_load_evaluation_cases_rejects_empty_relevance(tmp_path: Path) -> None:
    corpus = tmp_path / "evaluation.yaml"
    corpus.write_text(
        "cases:\n  - question: How do I install?\n    relevant_chunks: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="relevant_chunks"):
        load_evaluation_cases(corpus)


def test_committed_evaluation_corpus_has_fifty_source_addressable_cases() -> None:
    corpus_path = Path(__file__).parents[1] / "src/modelable/rag/evaluation_corpus.yaml"

    cases = load_evaluation_cases(corpus_path)

    assert len(cases) == 50
    assert all("#" in chunk_id for case in cases for chunk_id in case.relevant_chunk_ids)
    assert {case.category for case in cases} == {"challenge", "lexical"}


def test_committed_evaluation_corpus_ids_exist_in_documentation() -> None:
    corpus_path = Path(__file__).parents[1] / "src/modelable/rag/evaluation_corpus.yaml"
    documentation_path = Path(__file__).parents[2] / "docs"
    cases = load_evaluation_cases(corpus_path)
    available_ids = {chunk.external_id for chunk in load_documentation_chunks(documentation_path)}

    missing = {chunk_id for case in cases for chunk_id in case.relevant_chunk_ids if chunk_id not in available_ids}
    assert missing == set()
