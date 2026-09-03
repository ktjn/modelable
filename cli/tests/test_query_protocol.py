import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modelable.query_protocol import (
    QUERY_SCHEMA,
    QueryProtocolError,
    serialize_query_response,
    validate_query_request,
    validate_query_response,
)


def test_query_request_normalizes_defaults_and_preserves_order_independent_data() -> None:
    request = validate_query_request(
        {
            "$schema": QUERY_SCHEMA,
            "kind": "query",
            "query": "declaration",
            "id": "customer.Customer@1",
        }
    )

    assert request == {
        "$schema": QUERY_SCHEMA,
        "kind": "query",
        "query": "declaration",
        "id": "customer.Customer@1",
        "limit": 100,
    }


def test_query_response_serializes_canonically() -> None:
    response = {
        "$schema": QUERY_SCHEMA,
        "kind": "query_result",
        "query": "declaration",
        "data": {"id": "customer.Customer@1", "kind": "model"},
    }

    serialized = serialize_query_response(response)

    assert json.loads(serialized) == response
    assert serialized == json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert validate_query_response(json.loads(serialized)) == response


def test_lifecycle_query_family_requires_an_identity() -> None:
    request = validate_query_request(
        {
            "$schema": QUERY_SCHEMA,
            "kind": "query",
            "query": "lifecycle",
            "id": "customer.Customer@1",
        }
    )

    assert request["query"] == "lifecycle"


def test_checked_in_query_schema_is_valid() -> None:
    schema_path = Path(__file__).parents[1] / "src" / "modelable" / "data" / "modelable.query.v1.schema.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    fixture_root = Path(__file__).parent / "golden" / "query" / "v1"
    validator.validate(json.loads((fixture_root / "declaration.request.json").read_text(encoding="utf-8")))
    validator.validate(json.loads((fixture_root / "declaration.response.json").read_text(encoding="utf-8")))


def test_query_response_allows_additive_optional_members() -> None:
    response = {
        "$schema": QUERY_SCHEMA,
        "kind": "query_result",
        "query": "declaration",
        "data": {},
        "future_metadata": {"server": "new"},
    }

    assert validate_query_response(response) == response
    schema_path = Path(__file__).parents[1] / "src" / "modelable" / "data" / "modelable.query.v1.schema.json"
    Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(response)


@pytest.mark.parametrize(
    "document",
    [
        {"$schema": QUERY_SCHEMA, "kind": "query", "query": "unknown", "id": "customer.Customer@1"},
        {"$schema": QUERY_SCHEMA, "kind": "query", "query": "declaration"},
        {
            "$schema": QUERY_SCHEMA,
            "kind": "query",
            "query": "declaration",
            "id": "customer.Customer@1",
            "limit": 0,
        },
        {"$schema": QUERY_SCHEMA, "kind": "query", "query": "declaration", "id": "customer.Customer@1", "extra": 1},
    ],
)
def test_query_request_rejects_invalid_envelopes(document: dict[str, object]) -> None:
    with pytest.raises(QueryProtocolError):
        validate_query_request(document)
