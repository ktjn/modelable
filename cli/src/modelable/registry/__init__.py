__all__ = ["build_registry"]


def __getattr__(name: str):
    if name == "build_registry":
        from modelable.registry.index import build_registry

        return build_registry
    raise AttributeError(name)
