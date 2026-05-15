import pytest

from modelable.parser.ir import ParseError


def test_compile_valid_model():
    from modelable.compiler.compiler import compile_text

    mdl, errors = compile_text("""
    domain customer {
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
    }
    """)

    assert errors == []
    assert mdl.domains[0].name == "customer"


def test_compile_returns_errors_not_raises():
    from modelable.compiler.compiler import compile_text

    mdl, errors = compile_text("""
    domain customer {
      entity Customer @ 1 (additive) {
        customerId: uuid
      }
    }
    """)

    assert mdl.domains[0].name == "customer"
    assert any("key" in error.lower() for error in errors)


def test_compile_file(fixture_path):
    from modelable.compiler.compiler import compile_file

    mdl, errors = compile_file(fixture_path / "customer.mdl")

    assert errors == []
    assert mdl.domains[0].name == "customer"


def test_compile_parse_error_raises():
    from modelable.compiler.compiler import compile_text

    with pytest.raises(ParseError):
        compile_text("domain { broken yaml }")
