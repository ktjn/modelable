# Using Modelable From Another Project

Consumer projects normally need the Python package for CLI and language-server
support. The VS Code extension and generated artifacts are optional.

## Install the CLI and language server

Modelable requires Python 3.14.

```bash
uv add --dev modelable
```

For a user-level command:

```bash
uv tool install modelable
```

Pin a specific release when reproducibility matters:

```bash
uv add --dev "modelable==0.5.0"
```

Confirm the installation:

```bash
modelable --version
modelable --help
modelable lsp --help
```

Release pages include the wheel, source distribution, SHA-256 checksums, and a
machine-readable manifest. PyPI trusted publishing is the primary installation
path; GitHub assets provide an independently inspectable copy of the build.

## Install the VS Code extension

Download `modelable-vscode-<version>.vsix` from the matching GitHub release and
install it with:

```bash
code --install-extension modelable-vscode-0.5.0.vsix
```

The extension first uses `modelable.serverCommand`, then
`modelable.pythonPath`, then a development-checkout virtual environment, and
finally `modelable lsp` from `PATH`. A normal consumer project should install
the Python package and let the extension find `modelable` on `PATH`, or set an
explicit command when the environment is unusual.

## Generate artifacts in the consumer build

Generate artifacts from the project's `.mdl` source instead of copying source
code from this repository:

```bash
modelable validate models --strict
modelable compile models --target json-schema --out generated/jsonschema
modelable compile models --target typescript --out generated/typescript
```

Whether generated output is committed should follow the consumer repository's
normal policy. Always pin the Modelable version in CI so compiler and emitter
changes are deliberate.

Before upgrading, read [CHANGELOG.md](../CHANGELOG.md) for changes to `.mdl`
syntax, CLI behavior, compatibility rules, or generated output.
