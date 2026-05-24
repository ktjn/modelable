from modelable.expressions.cel import (
    BinaryOp,
    CelContext,
    FieldRef,
    FunctionCall,
    Literal,
    TernaryOp,
    extract_field_refs,
    parse_cel,
    validate_cel_expr,
)
import pytest


# ── Parser tests ──────────────────────────────────────────────────────────────


def test_parse_simple_comparison():
    ast, errors = parse_cel('c.status == "active"')
    assert errors == []
    assert isinstance(ast, BinaryOp)
    assert ast.op == "=="
    assert isinstance(ast.left, FieldRef)
    assert ast.left.alias == "c"
    assert ast.left.field == "status"
    assert isinstance(ast.right, Literal)
    assert ast.right.value == "active"


def test_parse_boolean_literal():
    ast, errors = parse_cel("true")
    assert errors == []
    assert isinstance(ast, Literal)
    assert ast.value is True


def test_parse_null_literal():
    ast, errors = parse_cel("null")
    assert errors == []
    assert isinstance(ast, Literal)
    assert ast.value is None


def test_parse_ternary():
    ast, errors = parse_cel('c.flag ? "yes" : "no"')
    assert errors == []
    assert isinstance(ast, TernaryOp)


def test_parse_logical_and():
    ast, errors = parse_cel('c.a == "x" && c.b == "y"')
    assert errors == []
    assert isinstance(ast, BinaryOp)
    assert ast.op == "&&"


def test_parse_function_call():
    ast, errors = parse_cel("lower(c.name)")
    assert errors == []
    assert isinstance(ast, FunctionCall)
    assert ast.name == "lower"
    assert len(ast.args) == 1


def test_parse_in_operator():
    ast, errors = parse_cel('c.status in ["active", "pending"]')
    assert errors == []
    assert isinstance(ast, BinaryOp)
    assert ast.op == "in"


def test_parse_error_incomplete():
    ast, errors = parse_cel("c.status ==")
    assert ast is None
    assert any("CEL001" in e for e in errors)


def test_parse_error_bad_token():
    ast, errors = parse_cel("@@@")
    assert ast is None
    assert any("CEL001" in e for e in errors)


# ── Validation tests ──────────────────────────────────────────────────────────


def _ctx(fields: dict[str, set[str]], has_group_by: bool = False) -> CelContext:
    return CelContext(source_fields=fields, has_group_by=has_group_by, fqn="test.Proj@1")


def test_valid_field_ref():
    ast, _ = parse_cel('c.status == "active"')
    result = validate_cel_expr(ast, _ctx({"c": {"status"}}))
    assert result.errors == []
    assert ("c", "status") in result.field_refs


def test_unknown_alias():
    ast, _ = parse_cel('x.field == "value"')
    result = validate_cel_expr(ast, _ctx({"c": {"field"}}))
    assert any("CEL002" in e and "unknown alias 'x'" in e for e in result.errors)


def test_unknown_field():
    ast, _ = parse_cel('c.missing == "value"')
    result = validate_cel_expr(ast, _ctx({"c": {"status", "name"}}))
    assert any("CEL002" in e and "c.missing" in e for e in result.errors)


def test_bare_identifier_rejected():
    ast, _ = parse_cel("status")
    result = validate_cel_expr(ast, _ctx({"c": {"status"}}))
    assert any("CEL002" in e for e in result.errors)


def test_unsupported_function():
    ast, _ = parse_cel("myCustomFunc(c.name)")
    result = validate_cel_expr(ast, _ctx({"c": {"name"}}))
    assert any("CEL005" in e and "myCustomFunc" in e for e in result.errors)


def test_non_deterministic_function():
    ast, _ = parse_cel("random()")
    result = validate_cel_expr(ast, _ctx({}))
    assert any("CEL007" in e and "random" in e for e in result.errors)


def test_now_is_allowed():
    ast, errors = parse_cel("now()")
    assert errors == []
    result = validate_cel_expr(ast, _ctx({}))
    assert not any("CEL007" in e for e in result.errors)
    assert not any("CEL005" in e for e in result.errors)


def test_aggregate_without_group_by():
    ast, _ = parse_cel("sum(c.amount)")
    result = validate_cel_expr(ast, _ctx({"c": {"amount"}}, has_group_by=False))
    assert any("CEL006" in e for e in result.errors)


def test_aggregate_with_group_by_is_valid():
    ast, _ = parse_cel("sum(c.amount)")
    result = validate_cel_expr(ast, _ctx({"c": {"amount"}}, has_group_by=True))
    assert not any("CEL006" in e for e in result.errors)


def test_valid_scalar_functions():
    for func in ["lower", "upper", "trim", "toString", "coalesce"]:
        ast, _ = parse_cel(f'{func}(c.name)')
        result = validate_cel_expr(ast, _ctx({"c": {"name"}}))
        assert not any("CEL005" in e for e in result.errors), f"{func} should be allowed"


def test_slice_is_valid_function():
    ast, errors = parse_cel("slice(c.code, 0, 3)")
    assert errors == []
    assert isinstance(ast, FunctionCall)
    assert ast.name == "slice"
    result = validate_cel_expr(ast, _ctx({"c": {"code"}}))
    assert result.errors == []
    assert ("c", "code") in result.field_refs


def test_slice_lineage_extraction():
    ast, _ = parse_cel("slice(c.code, 0, 3)")
    refs = extract_field_refs(ast)
    assert ("c", "code") in refs


def test_runtime_ref_accepted():
    ast, _ = parse_cel("request.sellerId")
    result = validate_cel_expr(ast, _ctx({}))
    assert result.errors == []


# ── Lineage extraction ────────────────────────────────────────────────────────


def test_extract_refs_from_comparison():
    ast, _ = parse_cel('c.status == "active"')
    refs = extract_field_refs(ast)
    assert ("c", "status") in refs


def test_extract_multiple_refs():
    ast, _ = parse_cel("c.status == \"active\" && c.name != \"deleted\"")
    refs = extract_field_refs(ast)
    assert ("c", "status") in refs
    assert ("c", "name") in refs


def test_extract_refs_from_ternary():
    ast, _ = parse_cel('c.flag ? c.a : c.b')
    refs = extract_field_refs(ast)
    assert ("c", "flag") in refs
    assert ("c", "a") in refs
    assert ("c", "b") in refs


def test_extract_refs_from_function():
    ast, _ = parse_cel("lower(c.name)")
    refs = extract_field_refs(ast)
    assert ("c", "name") in refs


def test_extract_refs_from_multi_alias():
    ast, _ = parse_cel("c.customerId == o.customerId")
    refs = extract_field_refs(ast)
    assert ("c", "customerId") in refs
    assert ("o", "customerId") in refs


def test_no_refs_from_literal():
    ast, _ = parse_cel('"hello"')
    refs = extract_field_refs(ast)
    assert refs == []


# ── End-to-end via workspace ──────────────────────────────────────────────────


def test_workspace_rejects_invalid_cel():
    from modelable.compiler.workspace import load_workspace
    from pathlib import Path
    import tempfile, textwrap

    mdl_text = textwrap.dedent("""\
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          projection BadProj @ 1
            from customer.Customer @ 1 as c
          {
            result = unknownFunc(c.status)
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        mdl_path = Path(tmp) / "test.mdl"
        mdl_path.write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    assert any("CEL005" in diagnostic.message for diagnostic in ws.errors)


def test_workspace_accepts_valid_cel():
    from modelable.compiler.workspace import load_workspace
    from pathlib import Path
    import tempfile, textwrap

    mdl_text = textwrap.dedent("""\
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            status: string
          }
        }
        domain billing {
          projection GoodProj @ 1
            from customer.Customer @ 1 as c
          {
            isActive = c.status == "active"
          }
        }
    """)
    with tempfile.TemporaryDirectory() as tmp:
        mdl_path = Path(tmp) / "test.mdl"
        mdl_path.write_text(mdl_text, encoding="utf-8")
        ws = load_workspace(tmp)
    cel_errors = [diagnostic.message for diagnostic in ws.errors if "CEL" in diagnostic.code]
    assert cel_errors == []


# ── New function and syntax tests ─────────────────────────────────────────────


def test_parse_where_clause():
    ast, errors = parse_cel('sum(c.amount) where c.status == "active"')
    assert errors == []
    assert isinstance(ast, FunctionCall)
    assert ast.name == "sum"
    assert ast.where_filter is not None
    assert isinstance(ast.where_filter, BinaryOp)


def test_where_clause_field_refs_extracted():
    ast, _ = parse_cel('sum(c.amount) where c.status == "active"')
    refs = extract_field_refs(ast)
    assert ("c", "amount") in refs
    assert ("c", "status") in refs


def test_where_clause_validated():
    ast, _ = parse_cel('sum(c.amount) where c.status == "active"')
    result = validate_cel_expr(ast, _ctx({"c": {"amount", "status"}}, has_group_by=True))
    assert result.errors == []


def test_where_clause_unknown_field_in_filter():
    ast, _ = parse_cel('sum(c.amount) where c.missing == "x"')
    result = validate_cel_expr(ast, _ctx({"c": {"amount"}}, has_group_by=True))
    assert any("CEL002" in e and "c.missing" in e for e in result.errors)


def test_aggregate_functions_valid():
    for func in ["countif", "count_distinct", "mode"]:
        ast, errors = parse_cel(f"{func}(c.field)")
        assert errors == [], f"{func} should parse without errors"
        result = validate_cel_expr(ast, _ctx({"c": {"field"}}, has_group_by=True))
        assert not any("CEL005" in e for e in result.errors), f"{func} should be allowed"


def test_scalar_functions_valid():
    for func in ["date_diff", "truncate", "hmac_sha256", "decimal"]:
        ast, errors = parse_cel(f'{func}("arg", c.field)')
        assert errors == [], f"{func} should parse without errors"
        result = validate_cel_expr(ast, _ctx({"c": {"field"}}))
        assert not any("CEL005" in e for e in result.errors), f"{func} should be allowed"


def test_max_min_with_multiple_args_is_scalar_no_group_by_needed():
    for expr_str in ["max(c.a, c.b)", "min(c.x, c.y)"]:
        ast, errors = parse_cel(expr_str)
        assert errors == [], f"{expr_str} should parse"
        result = validate_cel_expr(ast, _ctx({"c": {"a", "b", "x", "y"}}, has_group_by=False))
        assert not any("CEL006" in e for e in result.errors), f"scalar {expr_str} should not require group by"


def test_max_with_single_arg_still_requires_group_by():
    ast, _ = parse_cel("max(c.amount)")
    result = validate_cel_expr(ast, _ctx({"c": {"amount"}}, has_group_by=False))
    assert any("CEL006" in e for e in result.errors)


def test_env_namespace_accepted():
    ast, errors = parse_cel("hmac_sha256(c.email, env.SECRET)")
    assert errors == []
    result = validate_cel_expr(ast, _ctx({"c": {"email"}}))
    assert result.errors == []


def test_countif_without_group_by_raises_cel006():
    ast, _ = parse_cel('countif(c.status == "active")')
    result = validate_cel_expr(ast, _ctx({"c": {"status"}}, has_group_by=False))
    assert any("CEL006" in e for e in result.errors)
