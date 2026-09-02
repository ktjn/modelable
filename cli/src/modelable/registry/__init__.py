__all__ = ["build_registry", "build_registry_from_snapshot"]


def __getattr__(name: str) -> object:
    if name in {"build_registry", "build_registry_from_snapshot"}:
        from modelable.registry.index import build_registry, build_registry_from_snapshot

        return build_registry if name == "build_registry" else build_registry_from_snapshot
    raise AttributeError(name)
