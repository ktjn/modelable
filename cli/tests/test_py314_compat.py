"""
Regression tests for the Python 3.14 pydantic compatibility shim.

pydantic 2.x calls typing._eval_type(..., prefer_fwd_module=True) when it
detects Python 3.14, but Python 3.14 RC2 renamed that parameter to
parent_fwdref. The shim in _pydantic_py314_compat.py patches typing._eval_type
to accept both names so pydantic model definitions succeed without modification.
"""
from __future__ import annotations

import sys
import typing

import pytest


@pytest.mark.skipif(sys.version_info < (3, 14), reason="Python 3.14+ only")
def test_shim_is_installed_before_pydantic_models():
    assert typing._eval_type.__name__ == "_compat_eval_type", (
        "_pydantic_py314_compat shim must be applied before any pydantic model imports; "
        "check that conftest.py imports modelable._pydantic_py314_compat first"
    )


@pytest.mark.skipif(sys.version_info < (3, 14), reason="Python 3.14+ only")
def test_shim_accepts_prefer_fwd_module_kwarg():
    result = typing._eval_type(
        str | None, {}, {}, (), prefer_fwd_module=None
    )
    assert result is not None


@pytest.mark.skipif(sys.version_info < (3, 14), reason="Python 3.14+ only")
def test_shim_translates_prefer_fwd_module_to_parent_fwdref():
    result = typing._eval_type(
        int | None, {}, {}, (), prefer_fwd_module=True
    )
    assert result is not None


def test_pydantic_ir_models_importable():
    from modelable.parser.ir import (
        DomainDef,
        FieldDef,
        MdlFile,
        ModelVersion,
        ProjectionVersion,
    )
    assert MdlFile is not None
    assert DomainDef is not None
    assert FieldDef is not None
    assert ModelVersion is not None
    assert ProjectionVersion is not None


def test_pydantic_model_instantiatable():
    from pydantic import BaseModel

    class _Probe(BaseModel):
        value: str

    obj = _Probe(value="ok")
    assert obj.value == "ok"
