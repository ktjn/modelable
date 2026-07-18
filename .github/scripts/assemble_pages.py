from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ORIGIN_ROOT_ASSET_URLS = ('src="/assets/', 'href="/assets/')


def _require_within_repository(path: Path, repository_root: Path) -> None:
    try:
        path.relative_to(repository_root)
    except ValueError as error:
        raise ValueError(f"Pages path escapes repository root: {path}") from error


def assemble_pages(site: Path, web_dist: Path) -> None:
    repository_root = Path.cwd().resolve()
    resolved_site = site.resolve()
    playground = resolved_site / "playground"
    resolved_playground = playground.resolve()

    _require_within_repository(resolved_site, repository_root)
    _require_within_repository(resolved_playground, repository_root)

    index = web_dist / "index.html"
    if not index.is_file():
        raise ValueError(f"Browser distribution is missing index.html: {index}")

    for html_path in web_dist.rglob("*.html"):
        html = html_path.read_text(encoding="utf-8")
        if any(asset_url in html for asset_url in ORIGIN_ROOT_ASSET_URLS):
            raise ValueError(f"Browser HTML contains an origin-root asset URL: {html_path}")

    if playground.exists():
        if not playground.is_dir() or playground.is_symlink():
            raise ValueError(f"Refusing to replace non-directory playground path: {playground}")
        shutil.rmtree(playground)

    shutil.copytree(web_dist, playground, dirs_exist_ok=False)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compose MkDocs and browser proof output for GitHub Pages.")
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    assemble_pages(args.site, args.web_dist)


if __name__ == "__main__":
    main()
