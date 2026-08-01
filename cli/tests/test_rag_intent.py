import pytest

from modelable.rag.intent import RetrievalRoute, classify_retrieval_intent


@pytest.mark.parametrize(
    ("message", "expected_route"),
    [
        ("How do I configure the registry?", "automatic_documentation"),
        ("What is the Modelable syntax for a projection?", "automatic_documentation"),
        ("Add a creditScore field to Customer", "none"),
        ("/compile --target json-schema", "none"),
        ("/docs How do I configure the registry?", "explicit_documentation"),
        (" /docs   explain the registry", "explicit_documentation"),
    ],
)
def test_classify_retrieval_intent_routes_table(message: str, expected_route: str) -> None:
    decision = classify_retrieval_intent(message)

    assert decision.route.value == expected_route


def test_classify_retrieval_intent_disables_automatic_routing() -> None:
    decision = classify_retrieval_intent("How do I configure the registry?", automatic_enabled=False)

    assert decision.route is RetrievalRoute.NONE
    assert decision.reason == "automatic_disabled"
    assert decision.question == ""


def test_classify_retrieval_intent_keeps_explicit_docs_when_automatic_disabled() -> None:
    decision = classify_retrieval_intent("/docs explain the registry", automatic_enabled=False)

    assert decision.route is RetrievalRoute.EXPLICIT_DOCUMENTATION
    assert decision.reason == "explicit_docs_command"
    assert decision.question == "explain the registry"


def test_classify_retrieval_intent_rejects_blank_docs_command() -> None:
    decision = classify_retrieval_intent("\u2003/docs\u00a0\u00a0")

    assert decision.route is RetrievalRoute.NONE
    assert decision.reason == "blank_docs_command"
    assert decision.question == ""


def test_classify_retrieval_intent_handles_unicode_whitespace_in_automatic_questions() -> None:
    decision = classify_retrieval_intent("How\u202fdo\u202fI configure the registry?")

    assert decision.route is RetrievalRoute.AUTOMATIC_DOCUMENTATION
    assert decision.reason == "automatic_documentation_signal"
    assert decision.question == "How do I configure the registry?"


def test_classify_retrieval_intent_leaves_ordinary_questions_alone() -> None:
    decision = classify_retrieval_intent("What are the supported targets?")

    assert decision.route is RetrievalRoute.NONE
    assert decision.reason == "no_documentation_signal"
    assert decision.question == ""
