# VS Code Smoke CI Gap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the existing VS Code smoke suite in CI and align repo guidance with the real LSP validation path so editor regressions stop landing silently.

**Status:** Complete

**Architecture:** Keep the current Python CLI validation job intact, add a separate VS Code smoke job that builds the checked-in extension and runs the Electron-based smoke tests under a headless display on Linux, then update the repo guidance documents so contributors and agents run the same gates locally and in PRs. Treat the smoke suite as a validation gate, not a new product surface.

**Tech Stack:** GitHub Actions, Node.js/npm, TypeScript, mocha, `@vscode/test-electron`, Python/pytest.

---

## File Map

**Modify:**
- `.github/workflows/validate.yml`
- `AGENTS.md`
- `docs/agent-governance.md`
- `docs/README.md`
- `vscode/README.md`

**Test / verify:**
- `vscode/src/test/runTests.ts`
- `vscode/src/test/suite/index.ts`
- `vscode/src/test/suite/lsp.test.ts`

---

### Task 1: Add the VS Code smoke suite to CI

**Files:**
- Modify: `.github/workflows/validate.yml`
- Test: `vscode/src/test/runTests.ts`
- Test: `vscode/src/test/suite/index.ts`
- Test: `vscode/src/test/suite/lsp.test.ts`

- [x] **Step 1: Add a second job to the existing validation workflow**

```yaml
  vscode:
    name: VS Code Smoke
    runs-on: ubuntu-latest

    defaults:
      run:
        working-directory: vscode

    steps:
      - name: Check out repository
        uses: actions/checkout@v6.0.1

      - name: Install Node
        uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: vscode/package-lock.json

      - name: Install extension dependencies
        run: npm ci

      - name: Build the smoke harness
        run: npm run build

      - name: Run VS Code smoke tests
        run: xvfb-run -a npm test
```

- [x] **Step 2: Run the smoke suite locally from the `vscode/` folder**

```powershell
cd vscode
npm ci
npm run build
npm test
```

Expected: the extension test runner launches the scenario workspace from `samples/scenarios/04-credit-risk-feature-store/` and the existing smoke assertions pass.

- [x] **Step 3: Commit the workflow change only after the smoke suite is green**

```bash
git add .github/workflows/validate.yml
git commit -m "ci: run vscode smoke tests in validate workflow"
```

---

### Task 2: Update repo guidance to require the same gate

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/agent-governance.md`
- Modify: `docs/README.md`
- Modify: `vscode/README.md`

- [x] **Step 1: Update `AGENTS.md` so the current-state guidance matches the real validation path**

Replace the stale milestone pointer with the actual current enforcement point:

```markdown
**Next task:** Enforce the VS Code smoke suite in CI and keep the LSP/editor guidance aligned with the shipped test harness.
```

Also update the local verification block so LSP/editor work points at both gates:

```markdown
cd cli
uv sync --extra dev
uv run pytest tests/ -v
uv run modelable validate ../samples/mvp

cd ..\vscode
npm ci
npm run build
npm test
```

- [x] **Step 2: Update `docs/agent-governance.md` to name the VS Code gate explicitly**

Add a test-gate row that says editor/LSP changes require both the Python protocol tests and the VS Code smoke suite:

```markdown
| LSP, VS Code extension, or editor integration | Focused LSP tests plus `cd vscode && npm ci && npm run build && npm test` |
```

Also add the same requirement to the local gate section:

```text
For editor/LSP changes, run:

cd cli
uv sync --extra dev
uv run pytest tests/test_lsp_*.py tests/test_lsp_integration.py -v

cd vscode
npm ci
npm run build
npm test
```

- [x] **Step 3: Update `docs/README.md` and `vscode/README.md` so the smoke suite is discoverable**

`docs/README.md` should mention that the LSP spec has a checked-in VS Code smoke suite and point readers to the `vscode/README.md` setup/run section.

`vscode/README.md` should call out the exact smoke commands and explain that CI runs the same suite headlessly on Linux:

```markdown
## Smoke tests

Run the extension smoke suite from this folder:

npm ci
npm run build
npm test

In CI the same suite runs under `xvfb-run -a npm test` on Ubuntu.
```

- [x] **Step 4: Review the Markdown diff for coherence and stale references**

Run: `git diff -- docs/README.md vscode/README.md AGENTS.md docs/agent-governance.md`

Expected: the new gate is mentioned consistently and there is no remaining reference that implies the VS Code smoke suite is optional.

---

### Task 3: Remove stale state that points future agents at the wrong work

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/mvp-implementation-plan.md` if any stale "next task" language remains there

- [x] **Step 1: Search for outdated milestone pointers and stale "next task" wording**

Run:

```powershell
rg -n "Next task:|Milestone 4|not started|partial" AGENTS.md docs/mvp-implementation-plan.md docs/README.md docs/agent-governance.md
```

Expected: the only remaining "partial" or "deferred" language is tied to genuinely deferred product work, not to the already-complete MVP milestone sequence.

- [x] **Step 2: Replace any stale pointer with the current enforcement gap**

Use this wording if `AGENTS.md` still points at the wrong milestone:

```markdown
**Next task:** Close the VS Code smoke CI gap and keep editor validation guidance in sync with the shipped LSP harness.
```

- [x] **Step 3: Final hygiene check**

Run:

```powershell
git status --short
git diff --check
```

Expected: only the intended documentation and workflow files changed, with no generated artifacts or unrelated files touched.
