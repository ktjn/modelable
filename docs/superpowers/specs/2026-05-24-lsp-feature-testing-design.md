# LSP Feature Testing Design

**Date:** 2026-05-24  
**Status:** Approved  
**Scope:** End-to-end validation of Modelable LSP features (hover, go-to-definition, references, completion) across sample scenarios, plus a VS Code extension smoke suite.

---

## Context

The existing test suite has two gaps:

1. `test_lsp_server.py` — only tests server initialization and debounce plumbing; never asserts on the content of LSP responses.
2. `test_lsp_integration.py` — uses `pytest-lsp` to run the full server, but only checks diagnostics (unresolved cross-domain references). None of the rich LSP features (hover, definition, completion, references) are validated.

Nine sample scenarios exist under `samples/scenarios/`. They are loaded by the server but not yet used as assertion fixtures in any test.

---

## Goals

- Validate that each major LSP feature returns correct content for real `.mdl` input.
- Use the existing sample scenarios as fixtures — one scenario per feature group where it is most representative.
- Confirm the VS Code extension activates and the end-to-end path (extension → language client → Python server) works.

---

## Architecture

### Two test layers

```
pytest-lsp (Python)          VS Code smoke (TypeScript/mocha)
─────────────────────        ──────────────────────────────────
Protocol-level assertions    Extension activation + UI path
Fast, CI-friendly            Slower, catches extension.js bugs
All features, many cases     3–4 smoke assertions only
```

---

## Layer 1: pytest-lsp Protocol Tests

### New file: `cli/tests/test_lsp_features.py`

Parallel to `test_lsp_integration.py`. Both files share the `lsp` fixture, which is extracted from `test_lsp_integration.py` into `cli/tests/conftest.py`.

### Shared fixture (conftest.py)

```python
@pytest_asyncio.fixture
async def lsp(request):
    workspace_root: Path = request.param
    client = make_test_lsp_client()
    await client.start_io(*SERVER_CMD)
    await client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=workspace_root.as_uri(),
            workspace_folders=[
                types.WorkspaceFolder(uri=workspace_root.as_uri(), name=workspace_root.name)
            ],
        )
    )
    yield client
    await client.shutdown_session()
```

### Helper utilities

```python
async def _hover(client, path: Path, line: int, char: int) -> str | None:
    """Returns the hover markdown string, or None."""

async def _definition(client, path: Path, line: int, char: int) -> tuple[str, int] | None:
    """Returns (uri, line) of the definition location, or None."""

async def _references(client, path: Path, line: int, char: int) -> list[tuple[str, int]]:
    """Returns list of (uri, line) for all reference locations."""

async def _completion_labels(client, path: Path, line: int, char: int) -> list[str]:
    """Returns the list of completion item labels."""
```

Each helper opens the file (if not already open) and fires the corresponding LSP request synchronously via the `pytest-lsp` client.

### Feature test matrix

#### Hover

| Test | Scenario | File | Position | Expected content |
|---|---|---|---|---|
| Hover over qualified cross-domain ref | 04-credit-risk | ml-credit-risk.mdl | `lending.LoanApplication @ 1` token | Markdown contains "LoanApplication" |
| Hover over model field with key flag | 04-credit-risk | ml-credit-risk.mdl | `applicationId` in projection body | Contains "key", field type |
| Hover over cross-domain alias field | 04-credit-risk | ml-credit-risk.mdl | `bur.creditScore` | Resolves via join alias to BureauReport.creditScore |
| Hover over model declaration name | 01-ecommerce | customer.mdl | Entity name token | Shows model summary |

#### Go-to-definition

| Test | Scenario | File | Position | Expected target |
|---|---|---|---|---|
| Definition of cross-domain type ref | 04-credit-risk | ml-credit-risk.mdl | `lending.LoanApplication @ 1` | lending.mdl, declaration line |
| Definition of cross-domain ref (sibling file) | 03-order-saga | shipping.mdl | `payments.PaymentAuthorisation` | payments.mdl, declaration line |
| Definition of field in same file | 01-ecommerce | customer.mdl | Field name inside entity body | Same file, field declaration line |

#### References

| Test | Scenario | File | Position | Expected |
|---|---|---|---|---|
| References to a type used across files | 01-ecommerce | customer.mdl | `Customer` entity name | All files referencing customer.Customer |
| References to a field within scope | 04-credit-risk | ml-credit-risk.mdl | `applicationId` in projection | Its usages in the file |

#### Completion

| Test | Scenario | File | Trigger position | Expected |
|---|---|---|---|---|
| `.` trigger after domain name | 05-marketplace | marketplace-api.mdl | After `inventory.` | Labels include `SellerInventoryLevel` |
| `@` trigger after model name | any | any | After model name + `@` | Version numbers appear in completions |

---

## Layer 2: VS Code Smoke Suite

### New files

```
vscode/
  tsconfig.json
  src/
    test/
      runTests.ts
      suite/
        index.ts
        lsp.test.ts
```

### Tooling additions to `vscode/package.json`

**devDependencies:**
- `@vscode/test-electron ^2`
- `mocha ^10`
- `@types/mocha`
- `typescript`

**scripts:**
```json
"build": "tsc -p tsconfig.json",
"test": "node ./out/test/runTests.js"
```

### `tsconfig.json`

```json
{
  "compilerOptions": {
    "module": "commonjs",
    "target": "es2020",
    "lib": ["es2020"],
    "outDir": "./out",
    "strict": true,
    "esModuleInterop": true
  },
  "include": ["src/**/*.ts"]
}
```

### `runTests.ts`

Uses `@vscode/test-electron` `runTests()`:
- `extensionDevelopmentPath` → `vscode/`
- `extensionTestsPath` → `vscode/out/test/suite/index`
- `launchArgs` → opens `samples/scenarios/04-credit-risk-feature-store/` as workspace

### `lsp.test.ts` — four smoke tests

1. **Extension activates** — `vscode.extensions.getExtension('modelable.modelable-vscode')` is not undefined and `isActive` is true after calling `activate()`.

2. **Hover returns content** — open `ml-credit-risk.mdl`, position cursor at `lending.LoanApplication @ 1`, call `vscode.commands.executeCommand('vscode.executeHoverProvider', uri, position)`, assert at least one hover with non-empty markdown value.

3. **Definition resolves cross-file** — same position, call `vscode.commands.executeCommand('vscode.executeDefinitionProvider', uri, position)`, assert result is a `Location` pointing to `lending.mdl`.

4. **No unresolved-reference diagnostics** — after a short wait (LSP publish delay), call `vscode.languages.getDiagnostics(uri)`, assert zero diagnostics whose message contains "unresolved model reference".

---

## Infrastructure Changes

### `cli/tests/conftest.py` (new)

Extract the `lsp` fixture and `SERVER_CMD` / `SCENARIOS` constants here so both integration test files share them without duplication.

### `cli/pyproject.toml`

Confirm `pytest-lsp` and `pytest-asyncio` are in `[project.optional-dependencies] dev`. No changes expected — they are already present.

### CI

- Python tests: `cd cli && pytest tests/test_lsp_features.py tests/test_lsp_integration.py` (existing CI step extended).
- VS Code tests: `cd vscode && npm run build && npm test` (new CI step; requires display server or `DISPLAY=:99` on Linux).

---

## Out of Scope

- Semantic tokens, formatting, rename, code actions, folding, inlay hints — not in this spec. Can be added in a follow-up.
- Performance / latency assertions.
- Windows-specific path edge cases in the VS Code layer (covered by unit tests in `workspace.py`).
