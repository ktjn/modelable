# Graph Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export the normalized Modelable workspace graph as deterministic JSON and expose it through `modelable graph export` with optional focus-based demo flows.

**Status:** Complete

**Architecture:** Keep graph extraction in a small helper under `cli/src/modelable/graph/` so the CLI wrapper, tests, and any later renderers share one canonical JSON shape. The first slice should include models, projections, fields, and field mappings only, with stable ordering and no runtime, registry, or governance expansion.

**Tech Stack:** Python 3.14, `click`, `pytest`, `json`, `pathlib`, existing `load_workspace` and reference-resolution helpers

---

### Task 1: Build the canonical graph export helper

**Files:**
- Create: `cli/src/modelable/graph/__init__.py`
- Create: `cli/src/modelable/graph/export.py`
- Test: `cli/tests/test_graph_export.py`

- [x] **Step 1: Write the failing export tests**

```python
from __future__ import annotations

import json
from pathlib import Path

from modelable.compiler.workspace import load_workspace
from modelable.graph.export import build_graph_export


def test_graph_export_includes_models_projections_and_mappings(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    displayName = c.name
  }
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    graph = build_graph_export(workspace)

    assert graph["kind"] == "workspace_graph"
    assert [node["kind"] for node in graph["nodes"]] == [
        "domain",
        "model",
        "model_version",
        "field",
        "field",
        "projection",
        "projection_version",
        "projection_field",
        "projection_field",
    ]
    assert any(edge["kind"] == "maps_to" for edge in graph["edges"])


def test_graph_export_is_deterministic(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""".strip(),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    first = json.dumps(build_graph_export(workspace), sort_keys=True)
    second = json.dumps(build_graph_export(workspace), sort_keys=True)

    assert first == second
```

- [x] **Step 2: Run the focused tests to confirm they fail**

Run:

```bash
cd cli
uv sync --extra dev
uv run pytest tests/test_graph_export.py -v
```

Expected:

- Fails because `modelable.graph.export` and the graph export helpers do not exist yet.

- [x] **Step 3: Implement the graph export helper**

Create `cli/src/modelable/graph/export.py` with a single canonical export path:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modelable.llm.context import parse_model_ref


def build_graph_export(workspace, focus: str | None = None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    focus_ref = parse_model_ref(focus) if focus is not None else None

    for domain in workspace.mdl.domains:
        _add_domain_graph(nodes, edges, domain)

    nodes.sort(key=lambda item: (item["kind"], item["id"]))
    edges.sort(key=lambda item: (item["kind"], item["source"], item["target"]))

    graph = {
        "kind": "workspace_graph",
        "nodes": nodes,
        "edges": edges,
    }
    if focus_ref is not None:
        graph["focus"] = {"domain": focus_ref.domain, "name": focus_ref.name, "version": focus_ref.version}
        graph = _filter_graph(graph, focus_ref)
    return graph


def write_graph_export(graph: dict[str, Any], out_path: Path) -> None:
    out_path.write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

Keep the export deterministic:

- stable node ordering,
- stable edge ordering,
- no timestamps,
- no file-system-specific paths,
- no registry or runtime metadata.

Focus handling should keep the neighborhood around the selected model or projection:

- model focus includes the model, its version, its fields, and projections that reference it,
- projection focus includes the projection, its source, its fields, and the mapped source fields,
- unrelated workspace nodes are omitted.

- [x] **Step 4: Re-run the focused export tests**

Run:

```bash
cd cli
uv run pytest tests/test_graph_export.py -v
```

Expected:

- The graph export tests pass.

- [x] **Step 5: Verify the helper against the full CLI gate**

Run:

```bash
cd cli
uv run pytest tests/ -v
uv run modelable validate ../samples/mvp --strict
git diff --check
```

Expected:

- Full CLI suite passes.
- MVP validation passes.
- Diff hygiene is clean.

- [x] **Step 6: Commit the graph export helper slice**

```bash
git add cli/src/modelable/graph/__init__.py cli/src/modelable/graph/export.py cli/tests/test_graph_export.py
git commit -m "feat: add graph export helper"
```

### Task 2: Wire `modelable graph export` into the CLI

**Files:**
- Create: `cli/src/modelable/commands/graph.py`
- Modify: `cli/src/modelable/cli.py`
- Test: `cli/tests/test_cli.py`

- [x] **Step 1: Write the failing CLI tests**

```python
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli


def test_graph_export_writes_json(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""".strip(),
        encoding="utf-8",
    )

    out = tmp_path / "graph.json"
    result = CliRunner().invoke(cli, ["graph", "export", str(tmp_path), "--out", str(out)])

    assert result.exit_code == 0, result.output
    graph = json.loads(out.read_text(encoding="utf-8"))
    assert graph["kind"] == "workspace_graph"
    assert any(node["kind"] == "model_version" for node in graph["nodes"])


def test_graph_export_focuses_on_projection(tmp_path: Path) -> None:
    mdl = tmp_path / "workspace.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    displayName = c.name
  }
}
""".strip(),
        encoding="utf-8",
    )

    out = tmp_path / "graph.json"
    result = CliRunner().invoke(
        cli,
        [
            "graph",
            "export",
            str(tmp_path),
            "--focus",
            "customer.CustomerView@1",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    graph = json.loads(out.read_text(encoding="utf-8"))
    assert any(node["kind"] == "projection_version" for node in graph["nodes"])
    assert any(edge["kind"] == "maps_to" for edge in graph["edges"])
```

- [x] **Step 2: Run the new CLI tests and confirm they fail for the right reason**

Run:

```bash
cd cli
uv run pytest tests/test_cli.py -v -k graph_export
```

Expected:

- Fails because `graph export` is not wired into the CLI yet.

- [x] **Step 3: Implement the CLI command group and registration**

Create `cli/src/modelable/commands/graph.py` with a focused command group:

```python
from __future__ import annotations

import json
from pathlib import Path

import click

from modelable.commands.common import console
from modelable.compiler.workspace import load_workspace
from modelable.graph.export import build_graph_export


@click.group()
def graph() -> None:
    """Graph export commands for the normalized workspace graph."""


def register_graph_commands(cli_group: click.Group) -> None:
    cli_group.add_command(graph)


@graph.command(name="export")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--focus", "focus", default=None, help="Optional model or projection ref to center the graph.")
@click.option("--out", "out_path", type=click.Path(path_type=Path), required=True)
def export_graph(source: Path, path: Path | None, focus: str | None, out_path: Path) -> None:
    workspace = load_workspace(path or source)
    graph = build_graph_export(workspace, focus=focus)
    write_graph_export(graph, out_path)
    console.print(f"[green]OK[/green] wrote {out_path}")
```

Update `cli/src/modelable/cli.py` to register the new group:

```python
from modelable.commands.graph import register_graph_commands

...
register_graph_commands(cli)
```

- [x] **Step 4: Re-run the CLI tests**

Run:

```bash
cd cli
uv run pytest tests/test_cli.py -v -k graph_export
```

Expected:

- `graph export` tests pass.

- [x] **Step 5: Re-run the full local gate**

Run:

```bash
cd cli
uv run pytest tests/ -v
uv run modelable validate ../samples/mvp --strict
git diff --check
```

Expected:

- Full CLI suite passes.
- MVP validation passes.
- Output and docs remain deterministic.

- [x] **Step 6: Commit the CLI slice**

```bash
git add cli/src/modelable/commands/graph.py cli/src/modelable/cli.py cli/tests/test_cli.py
git commit -m "feat: add graph export cli"
```

### Task 3: Update docs and graph demo guidance

**Files:**
- Modify: `docs/cli-spec.md`
- Modify: `docs/README.md`

- [x] **Step 1: Update the CLI spec with the new graph export command**

Add a new section near the existing lineage and registry export commands:

```md
### 10.8 `graph export` — Export the normalized model graph

```text
modelable graph export SOURCE [--path PATH] [--focus REF] [--out FILE]
```

Exports the normalized workspace graph as deterministic JSON for visualisation and inspection. `SOURCE` is a workspace path, file, or directory. `--path` follows the existing CLI source-discovery convention when the graph source needs an explicit workspace root. `--focus` narrows the graph to a model or projection and its immediate neighborhood. The command does not mutate source files.

**Examples:**

```bash
modelable graph export ./models --out ./dist/modelable-graph.json
modelable graph export ./models --focus customer.CustomerView@1 --out ./dist/customer-view-graph.json
modelable graph export ./models --path ./models --focus customer.CustomerView@1 --out ./dist/customer-view-graph.json
```
```

- [x] **Step 2: Add the graph export spec and plan to the docs index**

Update the documentation index so the new feature is discoverable:

```md
| [superpowers/specs/2026-05-31-graph-export-design.md](superpowers/specs/2026-05-31-graph-export-design.md) | Deterministic JSON export of the normalized model/projection graph for visualisation and demo flows | cli-spec.md, emitter-spec.md |
| [superpowers/plans/archived/2026-05-31-graph-export.md](superpowers/plans/archived/2026-05-31-graph-export.md) | Implementation plan for graph export JSON helper, CLI wiring, and docs updates | cli-spec.md, docs/README.md |
```

- [x] **Step 3: Review the Markdown diff for consistency**

Run:

```bash
git diff -- docs/cli-spec.md docs/README.md
```

Check:

- the new command is clearly separated from `registry graph` and `lineage export`,
- the docs say JSON is the canonical first slice,
- the demo flows match the CLI semantics,
- the docs index points at the new spec and plan.

- [x] **Step 4: Commit the docs slice**

```bash
git add docs/cli-spec.md docs/README.md
git commit -m "docs: add graph export docs"
```
