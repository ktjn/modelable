# GitHub Actions and Repository Gap Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update all live GitHub Actions to the verified latest stable releases and reconcile confirmed workflow, documentation, and plan-state drift.

**Architecture:** Keep the existing workflow structure and behavior unchanged while replacing only action release tags. Enforce the expected tags through repository-local text tests, then reconcile live documentation and archive completed plans without changing product behavior.

**Tech Stack:** GitHub Actions YAML, Python 3.14, pytest, uv, Markdown, npm, TypeScript

---

### Task 1: Add failing workflow-version policy tests

**Files:**
- Modify: `cli/tests/test_release_workflow.py`

- [ ] **Step 1: Add exact-version assertions for both live workflows**

Add constants for the repository root and expected action references. Extend the release test and add a validation-workflow test asserting:

```python
EXPECTED_ACTIONS = {
    "actions/checkout@v6.0.3",
    "actions/setup-python@v6.2.0",
    "actions/setup-node@v6.4.0",
    "astral-sh/setup-uv@v8.2.0",
    "softprops/action-gh-release@v3.0.0",
}
```

The release workflow must contain checkout, setup-python, setup-uv, and action-gh-release. The validation workflow must contain checkout, setup-uv, and setup-node. Each test must also reject older references by comparing the workflow's `uses:` values with its expected set.

- [ ] **Step 2: Run the focused test and verify red**

Run from `cli/`:

```text
uv run pytest tests/test_release_workflow.py -v
```

Expected: failures identify obsolete action references in the current workflow files.

### Task 2: Update live workflows and documentation example

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `.github/workflows/validate.yml`
- Modify: `docs/cli-tooling-spec.md`

- [ ] **Step 1: Replace action references**

Apply these exact substitutions everywhere in live workflows:

```text
actions/checkout@v6.0.3
actions/setup-python@v6.2.0
actions/setup-node@v6.4.0
astral-sh/setup-uv@v8.2.0
softprops/action-gh-release@v3.0.0
```

Do not modify workflow triggers, permissions, runner selection, cache settings, language versions, commands, or release inputs.

- [ ] **Step 2: Update the tooling-spec example**

Change the `docs/cli-tooling-spec.md` setup example from `astral-sh/setup-uv@v8.1.0` to `astral-sh/setup-uv@v8.2.0`.

- [ ] **Step 3: Run the focused tests and verify green**

Run from `cli/`:

```text
uv run pytest tests/test_release_workflow.py -v
```

Expected: all workflow policy tests pass.

### Task 3: Reconcile repository documentation and completed plans

**Files:**
- Modify: `README.md`
- Move: `docs/superpowers/plans/2026-06-11-json-passthrough-type.md`
- Move: `docs/superpowers/plans/2026-06-13-typescript-field-case-hint.md`
- Modify: `docs/superpowers/plans/archived/README.md`

- [ ] **Step 1: Correct README compatibility status**

Replace the Milestone 4 status with text stating that compatibility diff and cross-domain projection impact analysis are shipped.

- [ ] **Step 2: Reconcile the TypeScript plan checklist**

Replace every `- [ ]` task checkbox in `docs/superpowers/plans/2026-06-13-typescript-field-case-hint.md` with `- [x]`, matching the merged implementation history.

- [ ] **Step 3: Archive completed plans**

Move both active plan files into `docs/superpowers/plans/archived/` without changing their filenames.

- [ ] **Step 4: Index archived plans**

Append links for the JSON passthrough and TypeScript field-case plans to `docs/superpowers/plans/archived/README.md` in chronological order.

- [ ] **Step 5: Verify references**

Run:

```text
rg -n "docs/superpowers/plans/(2026-06-11-json-passthrough-type|2026-06-13-typescript-field-case-hint)" .
```

Expected: no live references point to the old active-plan paths.

### Task 4: Run local gates and review the change set

**Files:**
- Verify all modified files

- [ ] **Step 1: Run release-focused tests**

From `cli/`:

```text
uv sync --extra dev --frozen
uv run pytest tests/test_release_metadata.py tests/test_release_workflow.py -v
```

- [ ] **Step 2: Run the full CLI gate**

From `cli/`:

```text
uv run pytest tests/ --tb=short -q
uv run modelable validate ../samples/mvp --strict
```

- [ ] **Step 3: Run the VS Code gate**

From `vscode/`:

```text
npm ci
npm run build
npm test
```

- [ ] **Step 4: Review repository hygiene**

Run from the repository root:

```text
git diff --check
git status --short
git diff -- .github README.md docs cli/tests/test_release_workflow.py
```

Confirm that only the approved maintenance files changed, all live `uses:` references match the expected releases, and no transient output is included.
