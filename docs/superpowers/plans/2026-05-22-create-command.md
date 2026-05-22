# `create` Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `modelable create domain|model|projection` — interactive prompt wizards that write valid `.mdl` files.

**Architecture:** New file `cli/src/modelable/commands/create.py` with a Click group and three subcommands. Each prompts the user step-by-step using `click.prompt()` / `click.confirm()`, builds the `.mdl` text from pure string helpers, and writes it to `{output_dir}/{domain_name}.mdl`. Errors if the file already exists. No in-wizard validation — user runs `modelable validate` after.

**Tech Stack:** Python 3.14, Click 8.x (already a dependency), `pathlib.Path`, no new imports needed.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `cli/src/modelable/commands/create.py` | Create | `create` group + `domain`, `model`, `projection` subcommands + `.mdl` text generators |
| `cli/src/modelable/cli.py` | Modify | Import and register `create` |
| `cli/tests/test_cli_create.py` | Create | CliRunner tests for all three subcommands |

---

### Task 1: `create domain` subcommand

**Context:** Simplest subcommand — one prompt, one file. Establishes the module skeleton that Tasks 2 and 3 extend.

**Files:**
- Create: `cli/src/modelable/commands/create.py`
- Create: `cli/tests/test_cli_create.py`

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_cli_create.py`:

```python
from pathlib import Path

import pytest
from click.testing import CliRunner

from modelable.cli import cli


def test_create_domain_writes_mdl_file(tmp_path):
    result = CliRunner().invoke(
        cli, ["create", "domain", "--output-dir", str(tmp_path)], input="customer\n"
    )

    assert result.exit_code == 0
    out_file = tmp_path / "customer.mdl"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "domain customer {" in content


def test_create_domain_errors_if_file_exists(tmp_path):
    existing = tmp_path / "customer.mdl"
    existing.write_text("domain customer {}\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["create", "domain", "--output-dir", str(tmp_path)], input="customer\n"
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
```

- [ ] **Step 2: Run to verify they fail**

```
cd cli && .venv\Scripts\python -m pytest tests/test_cli_create.py -v
```

Expected: `FAIL` — `No such command 'create'`.

- [ ] **Step 3: Create `create.py` with the domain subcommand**

Create `cli/src/modelable/commands/create.py`:

```python
from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console


def register_create_commands(cli_group: click.Group) -> None:
    cli_group.add_command(create)


@click.group()
def create() -> None:
    """Create Modelable definition files interactively."""


@create.command(name="domain")
@click.option("--output-dir", "-d", default=".", type=click.Path(path_type=Path), show_default=True)
def create_domain(output_dir: Path) -> None:
    """Create a domain definition file."""
    name = click.prompt("Domain name")
    out_file = output_dir / f"{name}.mdl"
    if out_file.exists():
        raise click.ClickException(f"{out_file} already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(_domain_text(name), encoding="utf-8")
    console.print(f"[green]Created[/green] {out_file}")


def _domain_text(name: str) -> str:
    return f"domain {name} {{\n}}\n"
```

- [ ] **Step 4: Wire into `cli.py`**

Edit `cli/src/modelable/cli.py` — add one import and one register call:

```python
from modelable.commands.create import register_create_commands
```

Add after the other `register_*` calls:

```python
register_create_commands(cli)
```

- [ ] **Step 5: Run to verify tests pass**

```
cd cli && .venv\Scripts\python -m pytest tests/test_cli_create.py -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```
git add cli/src/modelable/commands/create.py cli/src/modelable/cli.py cli/tests/test_cli_create.py
git commit -m "feat: add create domain subcommand"
```

---

### Task 2: `create model` subcommand

**Context:** Walks the user through domain, kind, name, version, change_kind, then a field loop. Field loop terminates on a blank name. Builds model text from a pure helper function.

**Files:**
- Modify: `cli/src/modelable/commands/create.py`
- Modify: `cli/tests/test_cli_create.py`

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_cli_create.py`:

```python
def test_create_model_writes_entity_with_fields(tmp_path):
    # domain, kind, name, version (default=1), change_kind (default=additive),
    # field 1: name, type, optional?, @key?, @pii?,
    # field 2: name, type, optional?, @key?, @pii?,
    # blank name to finish
    user_input = "customer\nentity\nCustomer\n1\nadditive\ncustomerId\nuuid\nN\nY\nN\nemail\nstring\nY\nN\nN\n\n"

    result = CliRunner().invoke(
        cli, ["create", "model", "--output-dir", str(tmp_path)], input=user_input
    )

    assert result.exit_code == 0, result.output
    out_file = tmp_path / "customer.mdl"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "domain customer {" in content
    assert "entity Customer @ 1 (additive) {" in content
    assert "@key customerId: uuid" in content
    assert "email?: string" in content


def test_create_model_errors_if_file_exists(tmp_path):
    existing = tmp_path / "customer.mdl"
    existing.write_text("domain customer {}\n", encoding="utf-8")

    user_input = "customer\nentity\nCustomer\n1\nadditive\n\n"
    result = CliRunner().invoke(
        cli, ["create", "model", "--output-dir", str(tmp_path)], input=user_input
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
```

- [ ] **Step 2: Run to verify they fail**

```
cd cli && .venv\Scripts\python -m pytest tests/test_cli_create.py::test_create_model_writes_entity_with_fields tests/test_cli_create.py::test_create_model_errors_if_file_exists -v
```

Expected: `FAIL` — `No such command 'model'`.

- [ ] **Step 3: Add the `model` subcommand and its text generator**

Add to `cli/src/modelable/commands/create.py` (after `_domain_text`):

```python
_FIELD_TYPES = [
    "string", "int", "float", "bool", "date", "time",
    "timestamp", "uuid", "duration", "binary", "decimal",
]


@create.command(name="model")
@click.option("--output-dir", "-d", default=".", type=click.Path(path_type=Path), show_default=True)
def create_model(output_dir: Path) -> None:
    """Create a model (entity/aggregate/event/value) definition file."""
    domain = click.prompt("Domain name")
    kind = click.prompt("Model kind", type=click.Choice(["entity", "aggregate", "event", "value"]))
    name = click.prompt("Model name")
    version = click.prompt("Version", default=1, type=int)
    change_kind = click.prompt("Change kind", type=click.Choice(["additive", "breaking"]), default="additive")

    fields: list[dict] = []
    while True:
        field_name = click.prompt("Field name (leave blank to finish)", default="", show_default=False)
        if not field_name:
            break
        field_type = click.prompt("Field type", type=click.Choice(_FIELD_TYPES))
        optional = click.confirm("Optional field?", default=False)
        is_key = click.confirm("Add @key annotation?", default=False)
        is_pii = click.confirm("Add @pii annotation?", default=False)
        fields.append({"name": field_name, "type": field_type, "optional": optional, "is_key": is_key, "is_pii": is_pii})

    out_file = output_dir / f"{domain}.mdl"
    if out_file.exists():
        raise click.ClickException(f"{out_file} already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(_model_text(domain, kind, name, version, change_kind, fields), encoding="utf-8")
    console.print(f"[green]Created[/green] {out_file}")


def _model_text(
    domain: str,
    kind: str,
    name: str,
    version: int,
    change_kind: str,
    fields: list[dict],
) -> str:
    lines = [f"domain {domain} {{", f"  {kind} {name} @ {version} ({change_kind}) {{"]
    for field in fields:
        annotations = ""
        if field.get("is_key"):
            annotations += "@key "
        if field.get("is_pii"):
            annotations += "@pii "
        optional_marker = "?" if field.get("optional") else ""
        lines.append(f"    {annotations}{field['name']}{optional_marker}: {field['type']}")
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify tests pass**

```
cd cli && .venv\Scripts\python -m pytest tests/test_cli_create.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add cli/src/modelable/commands/create.py cli/tests/test_cli_create.py
git commit -m "feat: add create model subcommand"
```

---

### Task 3: `create projection` subcommand

**Context:** Prompts for domain, name, version, then a source model ref + version + alias. Then a field loop where the user enters `alias.field` for direct mappings or any other expression for computed mappings. Terminates on a blank field name.

**Files:**
- Modify: `cli/src/modelable/commands/create.py`
- Modify: `cli/tests/test_cli_create.py`

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_cli_create.py`:

```python
def test_create_projection_writes_projection_with_direct_and_computed_fields(tmp_path):
    # domain, name, version, source_model, source_version, alias,
    # field 1: name, mapping (direct alias.field),
    # field 2: name, mapping (CEL expression),
    # blank name to finish
    user_input = (
        "billing\n"           # domain
        "BillingCustomer\n"   # projection name
        "1\n"                 # version
        "customer.Customer\n" # source model ref
        "1\n"                 # source version
        "c\n"                 # alias
        "billingId\n"         # field 1 name
        "c.customerId\n"      # field 1 mapping (direct)
        "displayEmail\n"      # field 2 name
        "c.email + ''\n"      # field 2 mapping (computed)
        "\n"                  # blank = done
    )

    result = CliRunner().invoke(
        cli, ["create", "projection", "--output-dir", str(tmp_path)], input=user_input
    )

    assert result.exit_code == 0, result.output
    out_file = tmp_path / "billing.mdl"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "projection BillingCustomer @ 1" in content
    assert "from customer.Customer @ 1 as c" in content
    assert "billingId <- c.customerId" in content
    assert "displayEmail = c.email + ''" in content


def test_create_projection_errors_if_file_exists(tmp_path):
    existing = tmp_path / "billing.mdl"
    existing.write_text("domain billing {}\n", encoding="utf-8")

    user_input = "billing\nBillingCustomer\n1\ncustomer.Customer\n1\nc\n\n"
    result = CliRunner().invoke(
        cli, ["create", "projection", "--output-dir", str(tmp_path)], input=user_input
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
```

- [ ] **Step 2: Run to verify they fail**

```
cd cli && .venv\Scripts\python -m pytest tests/test_cli_create.py::test_create_projection_writes_projection_with_direct_and_computed_fields tests/test_cli_create.py::test_create_projection_errors_if_file_exists -v
```

Expected: `FAIL` — `No such command 'projection'`.

- [ ] **Step 3: Add the `projection` subcommand and its text generator**

Add to `cli/src/modelable/commands/create.py` (add `import re` at the top of the file alongside the other imports, then add these functions after `_model_text`):

At the top of the file, the imports section should be:

```python
from __future__ import annotations

import re
from pathlib import Path

import click

from modelable.commands.common import console
```

Add these functions after `_model_text`:

```python
@create.command(name="projection")
@click.option("--output-dir", "-d", default=".", type=click.Path(path_type=Path), show_default=True)
def create_projection(output_dir: Path) -> None:
    """Create a projection definition file."""
    domain = click.prompt("Domain name")
    name = click.prompt("Projection name")
    version = click.prompt("Version", default=1, type=int)
    source_model = click.prompt("Source model ref (e.g. customer.Customer)")
    source_version = click.prompt("Source version", default=1, type=int)
    alias = click.prompt("Source alias")

    fields: list[dict] = []
    while True:
        field_name = click.prompt("Field name (leave blank to finish)", default="", show_default=False)
        if not field_name:
            break
        mapping = click.prompt("Mapping (alias.field for direct, or CEL expression)")
        fields.append({"name": field_name, "mapping": mapping})

    out_file = output_dir / f"{domain}.mdl"
    if out_file.exists():
        raise click.ClickException(f"{out_file} already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(
        _projection_text(domain, name, version, source_model, source_version, alias, fields),
        encoding="utf-8",
    )
    console.print(f"[green]Created[/green] {out_file}")


_DIRECT_MAPPING_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")


def _projection_text(
    domain: str,
    name: str,
    version: int,
    source_model: str,
    source_version: int,
    alias: str,
    fields: list[dict],
) -> str:
    lines = [
        f"domain {domain} {{",
        f"  projection {name} @ {version}",
        f"    from {source_model} @ {source_version} as {alias}",
        "  {",
    ]
    for field in fields:
        mapping = field["mapping"]
        if _DIRECT_MAPPING_RE.match(mapping):
            lines.append(f"    {field['name']} <- {mapping}")
        else:
            lines.append(f"    {field['name']} = {mapping}")
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify all tests pass**

```
cd cli && .venv\Scripts\python -m pytest tests/test_cli_create.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Run the full test suite to check for regressions**

```
cd cli && .venv\Scripts\python -m pytest tests/ -q --ignore=tests/test_codegen_docker_smoke.py --ignore=tests/test_llm_provider_integration.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```
git add cli/src/modelable/commands/create.py cli/tests/test_cli_create.py
git commit -m "feat: add create projection subcommand"
```

---

### Task 4: Update CLI help text

**Context:** The `cli.py` docstring lists the implemented commands. It should include `create` so `modelable --help` accurately reflects the available commands.

**Files:**
- Modify: `cli/src/modelable/cli.py`

- [ ] **Step 1: Update the docstring**

In `cli/src/modelable/cli.py`, update the CLI group docstring from:

```python
    """Modelable domain-owned data model compiler.

    MVP workflows cover validate, resolve, lineage, diff, compile, docs,
    inspect, codegen, lsp, and scenario helpers. Deferred command families such
    as Apicurio publish/pull, OpenMetadata export/publish, and ODCS export
    are documented in docs/cli-spec.md for later phases.
    """
```

to:

```python
    """Modelable domain-owned data model compiler.

    MVP workflows cover validate, resolve, lineage, diff, compile, docs,
    inspect, codegen, lsp, scenario, and create helpers. Deferred command
    families such as Apicurio publish/pull, OpenMetadata export/publish,
    and ODCS export are documented in docs/cli-spec.md for later phases.
    """
```

- [ ] **Step 2: Verify `--help` output**

```
cd cli && .venv\Scripts\python -m modelable --help
```

Expected: `create` appears in the command list.

- [ ] **Step 3: Commit**

```
git add cli/src/modelable/cli.py
git commit -m "docs: add create to CLI help text"
```
