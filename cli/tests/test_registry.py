from pathlib import Path

from modelable.registry.factory import get_registry
from modelable.registry.local import LocalRegistry


def test_local_registry(tmp_path: Path):
    registry_db = tmp_path / "registry.db"
    registry_db.write_text("dummy")

    registry_dir = tmp_path / "registry"
    registry_file = registry_dir / "registry.db"

    registry = LocalRegistry(registry_file)
    registry.push(registry_db)

    assert registry_file.exists()
    assert registry_file.read_text() == "dummy"

    dest = tmp_path / "pulled.db"
    registry.pull(dest)

    assert dest.exists()
    assert dest.read_text() == "dummy"


def test_factory_local(tmp_path: Path):
    registry_file = tmp_path / "registry.db"
    registry = get_registry(registry_file)
    assert isinstance(registry, LocalRegistry)
