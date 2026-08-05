from __future__ import annotations

from lark import Tree

from modelable.diagnostics.model import Diagnostic

_DEFERRED_BLOCK_MESSAGES: dict[str, str] = {
    "registry_block": (
        "`registry {}` is parsed but not enforced by the compiler; declared registry "
        "configuration has no effect. Deferred — see `modelable capabilities`."
    ),
    "peers_block": (
        "`peers: [...]` is parsed but not validated by the compiler; declared peer "
        "entries have no effect on compilation. Deferred — see `modelable capabilities`."
    ),
    "consumer_decl": (
        "`consumer {}` declarations are parsed but not tracked by the compiler; "
        "declared consumer registration has no effect. Deferred — see `modelable capabilities`."
    ),
    "subscription_block": (
        "`subscription {}` is parsed but the compiler implements no runtime "
        "subscription behavior; declared settings have no effect. Deferred — see "
        "`modelable capabilities`."
    ),
    "subscription_decl": (
        "`subscription NAME {}` is parsed but the compiler implements no runtime "
        "subscription behavior; declared settings have no effect. Deferred — see "
        "`modelable capabilities`."
    ),
    "materialisation_block": (
        "`materialisation {}` is parsed but the compiler implements no runtime "
        "materialization; declared settings have no effect. Deferred — see "
        "`modelable capabilities`."
    ),
}

_BINDING_OPAQUE_CONTENT_MESSAGE = (
    "unrecognized content inside `binding {}` is parsed but ignored; only `adapter`, "
    "`model`, and `table` are currently honored. Deferred — see `modelable capabilities`."
)


def find_deferred_syntax_diagnostics(tree: Tree, path: str) -> list[Diagnostic]:
    """Diagnose grammar constructs that parse successfully but are discarded before IR."""
    diagnostics = [
        Diagnostic(code="DEFERRED", message=message, severity="warning", path=path)
        for rule_name, message in _DEFERRED_BLOCK_MESSAGES.items()
        for _node in tree.find_data(rule_name)
    ]
    diagnostics.extend(
        Diagnostic(code="DEFERRED", message=_BINDING_OPAQUE_CONTENT_MESSAGE, severity="warning", path=path)
        for binding in tree.find_data("binding_decl")
        for item in binding.children
        if isinstance(item, Tree) and item.data == "binding_item"
        for child in item.children
        if isinstance(child, Tree) and child.data == "ignored_block_item"
    )
    return diagnostics
