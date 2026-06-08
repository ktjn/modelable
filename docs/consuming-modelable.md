# Consuming Modelable From Another Project

This document covers how to use Modelable's CLI/LSP, VS Code extension, and
generated artifacts **from a different repository that you control** — not
from inside this checkout. It assumes internal distribution: installing
directly from this repository's tagged releases and built artifacts, with no
public package index or marketplace publication involved.

There are three things a consumer project may want:

1. The `modelable` CLI and language server (a Python package).
2. The VS Code extension (an editor integration that wires the LSP).
3. Generated codegen artifacts (JSON Schema, TypeScript, Markdown docs, etc.).

## 1. Installing the CLI / LSP

`release.yml` already builds a wheel and sdist for every tagged release and
uploads them as GitHub release assets, alongside `SHA256SUMS` and
`release-manifest.json`. That's enough to install `modelable` into another
project's Python environment without standing up a private package index.

### Option A — install a tagged release wheel (recommended)

Pick a release tag (e.g. `v0.1.0`) and add it as a direct URL dependency:

```bash
# uv
uv add "modelable @ https://github.com/<org>/modelable/releases/download/v0.1.0/modelable-0.1.0-py3-none-any.whl"

# pip
pip install "https://github.com/<org>/modelable/releases/download/v0.1.0/modelable-0.1.0-py3-none-any.whl"
```

Verify the download against the published `SHA256SUMS` asset for that release
before trusting it in CI:

```bash
curl -sL -o SHA256SUMS https://github.com/<org>/modelable/releases/download/v0.1.0/SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS
```

### Option B — pin a git ref

If you'd rather build from source at a known commit or tag:

```bash
uv add "git+https://github.com/<org>/modelable.git@v0.1.0#subdirectory=cli"
```

This is slower (it builds the wheel locally) but avoids depending on release
assets existing.

### Pinning and upgrades

- Always pin to a release tag or commit SHA — never a branch — so the
  consumer project's environment is reproducible.
- Treat the published `release-manifest.json` (`package_version`,
  `commit_sha`, `git_tag`) as the authoritative record of what a given tag
  contains when deciding whether to upgrade.
- `requires-python = ">=3.14"` in `cli/pyproject.toml` — the consumer's
  environment must satisfy that constraint.

### Confirming the install

```bash
modelable --help
modelable lsp --help
```

If `modelable` doesn't resolve, make sure the project's virtual environment
(or the environment running `uv`/`pip`) is the one that's active.

## 2. Installing the VS Code extension

The extension lives in `vscode/` and is packaged as a `.vsix`:

```powershell
cd vscode
npm ci
npm run package
```

This produces `modelable-vscode.vsix`. Install it into another VS Code
instance with:

```powershell
code --install-extension modelable-vscode.vsix
```

The extension resolves the language server in this order: an explicit
`modelable.serverCommand` setting, an explicit `modelable.pythonPath`
setting, the repo-local `cli/.venv` (only present inside this checkout), then
`modelable` resolved from `PATH`. In a consumer project there is no
repo-local venv, so either:

- install the CLI into the consumer project's environment (Section 1) so
  `modelable` is on `PATH` and the extension finds it automatically, or
- set `modelable.pythonPath` to an interpreter that has `modelable` installed,
  or `modelable.serverCommand` to an explicit `[command, ...args]`, e.g.
  `["modelable", "lsp"]` or `["/path/to/venv/bin/python", "-m", "modelable.lsp"]`.

See [`vscode/README.md`](../vscode/README.md) for the full packaging and
configuration reference.

## 3. Consuming generated artifacts

`modelable compile` produces JSON Schema, Markdown docs, and typed-language
bindings (TypeScript, C#, Java, Python, Rust, Go) from `.mdl` sources. For
internal consumption, **run `compile` as part of the consumer project's own
build** rather than publishing pre-built artifacts:

```bash
modelable compile path/to/mdl-sources --target typescript --out generated/types
modelable compile path/to/mdl-sources --target json-schema --out generated/jsonschema
```

This keeps generated output in lockstep with the `.mdl` sources it was
derived from and avoids a staleness/sync problem between a published artifact
bundle and the model definitions that produced it. Publishing pre-built
artifacts as a separate package is possible later if a concrete consumer
requires it, but it isn't recommended as the default internal pattern.

## Agent instructions for consumer projects

If you are an AI agent working in a project that wants to integrate with
Modelable (not in the `modelable` repo itself), follow this sequence:

1. **Decide what's actually needed.** Most integrations only need the CLI
   (Section 1) to run `validate`/`compile` in the build. Only add the VS Code
   extension if the project's contributors edit `.mdl` files directly.
2. **Pin to a release tag**, not a branch — add the dependency exactly as
   shown in Section 1, Option A, recording the chosen tag in the consumer
   project's manifest/lockfile so the install is reproducible.
3. **Verify the install** with `modelable --help` before wiring it into a
   build step, and fail the setup loudly if the version doesn't match what
   was pinned.
4. **Wire `compile`/`validate` into the existing build**, rather than
   committing generated output, unless the consumer project already has an
   established convention of committing generated artifacts — match that
   convention if it exists.
5. **Don't vendor or copy source from this repo.** Always depend on a
   released wheel or a pinned git ref; copying source creates an untracked
   fork that can't receive fixes.
6. **If the LSP/extension is needed**, configure `modelable.pythonPath` or
   `modelable.serverCommand` explicitly (Section 2) — do not assume a
   repo-local venv exists, because it won't outside this checkout.
7. **When upgrading the pinned version**, check the target release's
   `release-manifest.json` and the project's changelog/PR history for
   breaking changes to CLI flags, emitter output, or `.mdl` syntax before
   bumping.
