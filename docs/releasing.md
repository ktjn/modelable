# Releasing Modelable

Releases are built from version tags and published by GitHub Actions. The tag,
Python package, VS Code extension, changelog, wheel, sdist, and VSIX must all
carry the same version.

## One-time repository setup

1. Create a protected GitHub environment named `pypi`.
2. Configure a PyPI pending trusted publisher for project `modelable`, owner
   `ktjn`, repository `modelable`, workflow `release.yml`, environment `pypi`.
3. Enable GitHub private vulnerability reporting.
4. Require the CLI and VS Code validation checks on `main`.

## Release checklist

1. Move user-facing entries from `Unreleased` into a dated version section.
2. Set the same version in `cli/pyproject.toml` and `vscode/package.json`.
3. Run the complete local gates documented in `CONTRIBUTING.md`.
4. Run the release workflow manually. Manual runs build and validate artifacts
   but do not publish them.
5. Merge the release pull request.
6. Create and push an annotated tag, for example `v0.5.0`.
7. Confirm the PyPI project, GitHub release, checksums, manifest, and VSIX.
8. Install the published wheel in a clean environment and run
   `modelable --version` plus strict MVP validation.

Do not rerun a failed publication blindly. Read the first failing release job,
fix the cause on a new commit, and publish a new version if any immutable
artifact already reached PyPI.
