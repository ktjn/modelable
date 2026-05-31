# Compatibility Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-domain compatibility engine for published model versions and expose it through `modelable diff` with deterministic output.

**Status:** Complete

**Architecture:** Keep the field comparison logic in `cli/src/modelable/compat/diff.py`, the status classification in `cli/src/modelable/compat/checker.py`, and the CLI rendering in `cli/src/modelable/commands/diff.py`. The first slice stays within one domain and one model name so the behavior is easy to validate and does not depend on cross-domain projection traversal.

**Tech Stack:** Python 3.14, `click`, `pytest`, existing `modelable` parser/registry/resolver modules

---

### Task 1: Stabilize compatibility reporting in the engine

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Modify: `cli/src/modelable/compat/checker.py`
- Test: `cli/tests/test_compatibility.py`

- [x] **Step 1: Write the failing tests**

```python
from modelable.compat.diff import compare_model_versions
from modelable.compat.checker import check_model_version_compatibility
from modelable.parser.parse import parse_text_to_ir


def _model_version(mdl_text: str, version: int = 1):
    mdl = parse_text_to_ir(mdl_text)
    domain = mdl.domains[0]
    model_name = next(iter(domain.models))
    return next(item for item in domain.models[model_name] if item.version == version)


def test_optional_field_addition_is_compatible():
    mdl = parse_text_to_ir(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            email?: string
          }
        }
        """
    )

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "compatible"
    assert any(change.kind == "added_field" and change.field_name == "email" for change in report.changes)
    assert any("added_field email" in finding for finding in report.findings)


def test_required_field_addition_is_breaking():
    mdl = parse_text_to_ir(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            email: string
          }
        }
        """
    )

    report = check_model_version_compatibility(mdl, "customer", "Customer", 1, 2)
    assert report.status == "breaking"
    assert any("added_field email" in finding for finding in report.findings)


def test_compare_model_versions_reports_stable_change_order():
    old_version = _model_version(
        """
        domain customer {
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
            status: enum(active, blocked)
          }
        }
        """
    )
    new_version = _model_version(
        """
        domain customer {
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            fullName: string
            status: string
            email?: string
          }
        }
        """,
        version=2,
    )

    changes = compare_model_versions(old_version, new_version)
    assert [change.kind for change in changes] == [
        "removed_field",
        "type_changed",
        "added_field",
        "added_field",
    ]
```

- [x] **Step 2: Run the focused tests to confirm they fail before implementation**

Run:

```bash
cd cli
uv sync --extra dev
uv run pytest tests/test_compatibility.py -v
```

Expected:

- Fails because the engine does not yet report the full single-domain compatibility contract required by the new tests.

- [x] **Step 3: Implement the minimal engine changes**

Make the engine deterministic and explicit:

```python
# cli/src/modelable/compat/diff.py
def compare_model_versions(old_version: ModelVersion, new_version: ModelVersion) -> list[FieldChange]:
    ...
    return changes


# cli/src/modelable/compat/checker.py
def check_model_version_compatibility(...):
    ...
    status = "breaking" if _has_breaking_change(changes, new_version) else "compatible"
    return CompatibilityReport(...)
```

Keep these rules:

- maintain stable output order,
- treat required-field additions as breaking,
- keep optional-field additions compatible,
- preserve rename, nullability, type, enum, and identity change reporting.

- [x] **Step 4: Re-run the focused compatibility tests**

Run:

```bash
cd cli
uv run pytest tests/test_compatibility.py -v
```

Expected:

- All compatibility tests pass.

- [x] **Step 5: Verify the engine against the full CLI gate**

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

- [x] **Step 6: Commit the compatibility engine slice**

```bash
git add cli/src/modelable/compat/diff.py cli/src/modelable/compat/checker.py cli/tests/test_compatibility.py
git commit -m "feat: stabilize compatibility engine"
```

### Task 2: Make `modelable diff` print the compatibility report deterministically

**Files:**
- Modify: `cli/src/modelable/commands/diff.py`
- Modify: `cli/tests/test_cli.py`
- Modify: `docs/cli-spec.md` if the command wording needs to be more explicit

- [x] **Step 1: Write the failing CLI tests**

```python
def test_diff_reports_breaking_changes(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
  }
}
        """.strip()
    )

    result = runner.invoke(cli, ["diff", "customer.Customer@1", "customer.Customer@2", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "customer.Customer@1 -> customer.Customer@2" in result.output
    assert "status: breaking" in result.output
    assert "- removed_field name" in result.output


def test_diff_supports_version_ranges(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    email?: string
  }
}
        """.strip()
    )

    result = runner.invoke(cli, ["diff", "customer.Customer@>=1<3", "customer.Customer@>=2<4", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "status: compatible" in result.output
    assert "- added_field email" in result.output
```

- [x] **Step 2: Run the new CLI tests to confirm they fail for the right reason**

Run:

```bash
cd cli
uv run pytest tests/test_cli.py -v
```

Expected:

- The `diff` assertions fail because the command output is still minimal and not yet fully deterministic.

- [x] **Step 3: Implement the CLI report formatting**

Update `cli/src/modelable/commands/diff.py` so it prints:

```python
console.print(f"{from_ref} -> {to_ref}")
console.print(f"status: {report.status}")
for finding in report.findings:
    console.print(f"- {finding}")
if not report.findings:
    console.print("- no changes")
```

Keep the same-domain/same-model ref check in place and preserve the existing lookup error handling.

Optionally update `docs/cli-spec.md` to state that `diff` reports a deterministic compatibility summary for two published versions in the same domain.

- [x] **Step 4: Re-run the CLI tests**

Run:

```bash
cd cli
uv run pytest tests/test_cli.py -v
```

Expected:

- `diff` tests pass.

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
git add cli/src/modelable/commands/diff.py cli/tests/test_cli.py docs/cli-spec.md
git commit -m "feat: wire compatibility diff cli"
```

### Task 3: Reconcile the milestone plan after the slice lands

**Files:**
- Modify: `docs/mvp-implementation-plan.md`

- [x] **Step 1: Update the milestone checklist**

Mark the compatibility-related Milestone 4 items that this slice completes, and leave projection/governance follow-up items untouched.

Suggested content:

```markdown
- [x] Compare consecutive model versions for additions, removals, renames, type changes, enum changes, identity changes, and nullability changes.
- [x] Implement `modelable diff REF_A REF_B --path PATH`.
```

- [x] **Step 2: Review the Markdown diff for consistency**

Run:

```bash
git diff -- docs/mvp-implementation-plan.md
```

Expected:

- The checklist reflects the shipped compatibility slice and does not claim projection or governance work is complete.

- [x] **Step 3: Commit the plan reconciliation**

```bash
git add docs/mvp-implementation-plan.md
git commit -m "docs: reconcile compatibility plan progress"
```
