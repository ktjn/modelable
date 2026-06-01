# Compatibility Impact Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement cross-domain projection impact analysis for `modelable diff`.

**Status:** Complete

**Architecture:**
- Add a dependency-finding helper to `cli/src/modelable/registry/resolver.py`.
- Add impact classification logic to `cli/src/modelable/compat/checker.py`.
- Update `cli/src/modelable/commands/diff.py` to display the impact report.

---

### Task 1: Find impacted projections via the registry

**Files:**
- Modify: `cli/src/modelable/registry/resolver.py`
- Test: `cli/tests/test_resolver.py`

- [x] **Step 1: Add `find_dependents` to the resolver**

```python
def find_dependents(workspace: Workspace, model_ref: str, version: int) -> list[tuple[str, str, int]]:
    """Return list of (domain, projection, version) depending on the source model version."""
    # Use SQLite query against projection_sources
```

- [x] **Step 2: Verify with unit tests**

---

### Task 2: Classify impact on projections

**Files:**
- Modify: `cli/src/modelable/compat/checker.py`
- Test: `cli/tests/test_compatibility.py`

- [x] **Step 1: Add `ProjectionImpact` dataclass**
- [x] **Step 2: Implement `analyze_impact(mdl, report, dependent_ref)`**
  - Check if any `FieldChange` in the report affects a field used by the dependent projection.

---

### Task 3: Update `modelable diff` CLI

**Files:**
- Modify: `cli/src/modelable/commands/diff.py`
- Test: `cli/tests/test_cli.py`

- [x] **Step 1: Update `run_diff` to call impact analysis**
- [x] **Step 2: Format and print the "Impacted Projections" section**

---

### Task 4: End-to-end validation with a new sample scenario

**Files:**
- Create: `samples/scenarios/10-impact-analysis/`
- Test: `cli/tests/test_samples.py`

- [x] **Step 1: Create a scenario with breaking model changes and downstream projections**
- [x] **Step 2: Add a smoke test verifying the CLI output for this scenario**

