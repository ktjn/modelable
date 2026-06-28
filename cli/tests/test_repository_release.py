from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_public_repository_files_exist() -> None:
    required = {
        "LICENSE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "ROADMAP.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/pull_request_template.md",
        ".github/dependabot.yml",
        ".github/workflows/codeql.yml",
    }

    missing = sorted(path for path in required if not (REPOSITORY_ROOT / path).is_file())
    assert missing == []


def test_python_package_has_stable_release_metadata() -> None:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "cli" / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["version"] == "1.0.0"
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert project["readme"] == "README.md"
    assert project["description"]
    assert project["authors"]
    assert project["maintainers"]
    assert project["urls"]["Repository"] == "https://github.com/ktjn/modelable"
    assert "Development Status :: 5 - Production/Stable" in project["classifiers"]
    assert "Programming Language :: Python :: 3.14" in project["classifiers"]


def test_extension_metadata_matches_release() -> None:
    package = json.loads((REPOSITORY_ROOT / "vscode" / "package.json").read_text(encoding="utf-8"))

    assert package["version"] == "1.0.0"
    assert package["license"] == "Apache-2.0"
    assert package["private"] is False


def test_release_versions_and_licenses_agree() -> None:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "cli" / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((REPOSITORY_ROOT / "vscode" / "package.json").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    assert package["version"] == version
    assert f"## [{version}]" in (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert (REPOSITORY_ROOT / "LICENSE").read_bytes() == (REPOSITORY_ROOT / "cli" / "LICENSE").read_bytes()
    assert (REPOSITORY_ROOT / "LICENSE").read_bytes() == (REPOSITORY_ROOT / "vscode" / "LICENSE").read_bytes()


def test_release_workflow_uses_trusted_publishing_and_builds_vsix() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "environment: pypi" in workflow
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert "npm run package" in workflow
    assert "*.vsix" in workflow
    assert "workflow_dispatch" in workflow
    assert "if: github.event_name == 'push'" in workflow


def test_docs_workflow_deploys_to_github_pages() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")

    assert "push" in workflow
    assert "main" in workflow
    assert "mkdocs" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "deploy-pages" in workflow


def test_public_docs_do_not_link_to_internal_plans() -> None:
    public_docs = [
        REPOSITORY_ROOT / "README.md",
        REPOSITORY_ROOT / "docs" / "README.md",
        REPOSITORY_ROOT / "docs" / "getting-started.md",
    ]

    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        assert "docs/superpowers" not in text
        assert "superpowers/" not in text
        assert "<org>" not in text
        assert "AI agent" not in text


def test_local_markdown_links_resolve() -> None:
    markdown_files = [
        *REPOSITORY_ROOT.glob("*.md"),
        *REPOSITORY_ROOT.glob("docs/*.md"),
        *REPOSITORY_ROOT.glob("samples/**/*.md"),
        REPOSITORY_ROOT / "vscode" / "README.md",
    ]
    failures: list[str] = []

    for source in markdown_files:
        text = source.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            destination = (source.parent / target).resolve()
            if not destination.exists():
                failures.append(f"{source.relative_to(REPOSITORY_ROOT)} -> {target}")

    assert failures == []
