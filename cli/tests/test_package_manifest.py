import json
from pathlib import Path

import pytest

from modelable.package_manifest import (
    PackageManifestError,
    load_package_manifest,
    normalize_package_manifest,
    package_content_hash,
    package_version_satisfies,
    resolve_package_manifests,
)

VALID = """
[package]
name = "customer.contracts"
version = "1.2.3"
description = "Public catalog contracts"

[exports]
declarations = ["catalog.Product@1", "catalog.Price@2"]

[dependencies]
"common.contracts" = ">=1.0.0,<2.0.0"
"identity.contracts" = ">=2,<3"
"""


def test_loads_package_identity_exports_and_dependencies(tmp_path: Path):
    path = tmp_path / "modelable.package.toml"
    path.write_text(VALID, encoding="utf-8")

    manifest = load_package_manifest(path)

    assert manifest.identity.name == "customer.contracts"
    assert manifest.identity.version == "1.2.3"
    assert manifest.exports == ("catalog.Price@2", "catalog.Product@1")
    assert [(item.name, item.constraint) for item in manifest.dependencies] == [
        ("common.contracts", ">=1.0.0,<2.0.0"),
        ("identity.contracts", ">=2,<3"),
    ]


def test_normalized_manifest_json_is_deterministic(tmp_path: Path):
    path = tmp_path / "modelable.package.toml"
    path.write_text(VALID, encoding="utf-8")

    manifest = load_package_manifest(path)

    assert json.dumps(normalize_package_manifest(manifest), indent=2, sort_keys=True) == json.dumps(
        {
            "package": {
                "name": "customer.contracts",
                "version": "1.2.3",
                "description": "Public catalog contracts",
            },
            "exports": {
                "declarations": ["catalog.Price@2", "catalog.Product@1"],
            },
            "dependencies": {
                "common.contracts": ">=1.0.0,<2.0.0",
                "identity.contracts": ">=2,<3",
            },
        },
        indent=2,
        sort_keys=True,
    )


def test_loads_domain_wildcard_exports(tmp_path: Path):
    path = tmp_path / "modelable.package.toml"
    path.write_text(
        '[package]\nname = "customer.contracts"\nversion = "1.2.3"\n\n[exports]\ndeclarations = ["customer.*"]\n',
        encoding="utf-8",
    )

    assert load_package_manifest(path).exports == ("customer.*",)


def test_package_content_hash_is_independent_of_source_order(tmp_path: Path):
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    first.write_text(VALID, encoding="utf-8")
    second.write_text(
        VALID.replace(
            '"common.contracts" = ">=1.0.0,<2.0.0"\n"identity.contracts" = ">=2,<3"',
            '"identity.contracts" = ">=2,<3"\n"common.contracts" = ">=1.0.0,<2.0.0"',
        ),
        encoding="utf-8",
    )

    assert package_content_hash(load_package_manifest(first)) == package_content_hash(load_package_manifest(second))
    assert len(package_content_hash(load_package_manifest(first))) == 64


def test_resolve_package_manifests_selects_highest_matching_local_version(tmp_path: Path):
    def manifest(name: str, version: str, dependency: str | None = None):
        path = tmp_path / f"{name}-{version}.toml"
        dependency_table = f'\n[dependencies]\n"identity.contracts" = "{dependency}"\n' if dependency else ""
        path.write_text(
            f'[package]\nname = "{name}"\nversion = "{version}"\n\n[exports]\ndeclarations = []\n{dependency_table}',
            encoding="utf-8",
        )
        return load_package_manifest(path)

    root = manifest("customer.contracts", "1.0.0", ">=2,<3")
    identity_old = manifest("identity.contracts", "2.1.0")
    identity_new = manifest("identity.contracts", "2.4.0")
    resolution = resolve_package_manifests((root, identity_old, identity_new))

    assert [f"{item.identity.name}@{item.identity.version}" for item in resolution.manifests] == [
        "customer.contracts@1.0.0",
        "identity.contracts@2.4.0",
    ]
    assert resolution.dependencies["customer.contracts@1.0.0"] == ("identity.contracts@2.4.0",)


def test_package_version_satisfies_partial_and_range_constraints() -> None:
    assert package_version_satisfies("2.4.0", ">=2,<3")
    assert package_version_satisfies("2.4.0", "2")
    assert not package_version_satisfies("3.0.0", ">=2,<3")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("[package]\nname = 'Catalog'\nversion = '1.0.0'\n", "invalid package name"),
        ("[package]\nname = 'catalog'\nversion = '1'\n", "invalid package version"),
        (
            "[package]\nname = 'catalog'\nversion = '1.0.0'\n[exports]\ndeclarations = ['not-an-id']\n",
            "invalid declaration identity",
        ),
        ("[package]\nname = 'catalog'\nversion = '1.0.0'\nunknown = true\n", "unknown key"),
        (
            "[package]\nname = 'catalog'\nversion = '1.0.0'\n[dependencies]\nCommon = '^1.0.0'\n",
            "invalid dependency name",
        ),
        (
            "[package]\nname = 'catalog'\nversion = '1.0.0'\n[dependencies]\nother = '>=2,<2'\n",
            "contradictory dependency constraint",
        ),
        ("[package]\nname = 'catalog'\nversion = '1.0.0-01'\n", "invalid package version"),
    ],
)
def test_rejects_invalid_manifest_content(tmp_path: Path, body: str, message: str):
    path = tmp_path / "modelable.package.toml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(PackageManifestError, match=message):
        load_package_manifest(path)
