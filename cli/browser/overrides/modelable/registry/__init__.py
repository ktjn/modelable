"""Browser-safe registry exports.

Registry construction depends on the desktop-only index module, so the browser
wheel deliberately exposes no registry factory.
"""

__all__: list[str] = []


def __getattr__(name: str) -> object:
    if name == "build_registry":
        raise AttributeError("modelable.registry.build_registry is unavailable in the browser wheel")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
