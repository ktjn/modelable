"""
Compatibility shim for pydantic 2.x on Python 3.14.

pydantic 2.x calls typing._eval_type(..., prefer_fwd_module=True) when it
detects Python 3.14, but Python 3.14 RC2 renamed that parameter to
parent_fwdref. This shim patches typing._eval_type to accept both names so
pydantic model definitions succeed without modification.
"""

from __future__ import annotations

import typing

_real_eval_type = typing._eval_type  # type: ignore[attr-defined]


def _compat_eval_type(
    t: object,
    globalns: object = None,
    localns: object = None,
    type_params: object = None,
    *,
    prefer_fwd_module: object = None,
    **kwargs: object,
) -> object:
    if prefer_fwd_module is not None:
        kwargs.setdefault("parent_fwdref", prefer_fwd_module)
    return _real_eval_type(t, globalns, localns, type_params=type_params, **kwargs)


typing._eval_type = _compat_eval_type  # type: ignore[attr-defined]
