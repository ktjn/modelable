from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_architecture_does_not_claim_unimplemented_model_lifecycle_status() -> None:
    architecture = _read("docs/architecture.md")

    assert "Mutable drafts may exist before publication" not in architecture
    assert "does not represent a model lifecycle status" in architecture


def test_compiler_reference_matches_clickhouse_index_support() -> None:
    compiler_reference = _read("docs/compiler-reference.md")

    assert "ClickHouse index DDL is deferred" not in compiler_reference
    assert "implemented as an inline data-skipping index" in compiler_reference


def test_integrations_reference_matches_protobuf_grpc_support() -> None:
    integrations = _read("docs/integrations.md")

    assert "descriptor sets and compatibility validation remain follow-up work" not in integrations
    assert "Avro, Protobuf, and Scalable-oriented gRPC generation are implemented" in integrations


def test_avro_documentation_matches_the_implemented_target() -> None:
    compiler_reference = _read("docs/compiler-reference.md")
    cli_reference = _read("docs/cli-reference.md")
    language_reference = _read("docs/language-reference.md")

    assert "| Avro | 5 | Implemented local artifact for model and event records |" in compiler_reference
    assert "`openapi`, `avro`, `registry`, or `event-sink`" in cli_reference
    assert "(`asyncapi` and the `mysql`/`sqlite` SQL dialects" in language_reference
