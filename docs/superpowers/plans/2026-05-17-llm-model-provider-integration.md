# LLM Model Provider Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace heuristic LLM stubs with a real model-backed assistant so natural-language generate, update, describe, ask, recommend, and transform workflows produce higher-quality proposals while still validating every write through Modelable's compiler pipeline.

**Architecture:** Introduce a provider-agnostic model client with one small contract for chat requests, structured outputs, retries, and usage reporting. The CLI should talk to that contract through the existing `modelable.llm` layer, so commands remain deterministic at the boundary: the model proposes text or structured edit intents, Modelable parses and validates the result, and only validated artifacts are written. Keep a local fallback path for non-networked use, but treat provider-backed generation as the primary path for quality.

**Tech Stack:** Python 3.12, `click`, `pydantic`, `lark`, existing `modelable.llm` modules, existing parser/validation pipeline, and a provider client that can target either hosted APIs or a local model runtime through the same interface.

---

### Task 1: Define the provider contract and configuration model

**Files:**
- Create: `cli/src/modelable/llm/providers.py`
- Modify: `cli/src/modelable/llm/config.py`
- Modify: `cli/src/modelable/llm/__init__.py`
- Test: `cli/tests/test_llm_provider_config.py`

- [ ] **Step 1: Write the failing tests for provider selection and config resolution**

```python
def test_provider_resolution_prefers_flag_over_env_over_workspace():
    assert resolve_provider(flag="openai", env="anthropic", workspace="local", default="fallback") == "openai"

def test_provider_config_requires_model_when_provider_enabled():
    with pytest.raises(ValueError, match="model"):
        resolve_runtime_config(provider="openai", model=None)
```

- [ ] **Step 2: Define the provider interface and runtime config**

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    schema: dict | None = None
    temperature: float = 0.2

@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
```

- [ ] **Step 3: Implement provider resolution and config loading**

```python
def resolve_provider(flag: str | None, env: str | None, workspace: str | None, default: str) -> str:
    return flag or env or workspace or default

def resolve_runtime_config(provider: str | None, model: str | None, api_key_env: str | None = None) -> RuntimeConfig:
    return RuntimeConfig(provider=provider or "local", model=model or "modelable-local", api_key_env=api_key_env)
```

- [ ] **Step 4: Run the focused config tests**

Run: `uv run pytest tests/test_llm_provider_config.py -v`
Expected: provider precedence and config validation pass.

- [ ] **Step 5: Commit**

```bash
git add cli/src/modelable/llm/providers.py cli/src/modelable/llm/config.py cli/src/modelable/llm/__init__.py cli/tests/test_llm_provider_config.py
git commit -m "feat: add model provider contract"
```

---

### Task 2: Add a real provider-backed completion path

**Files:**
- Create: `cli/src/modelable/llm/provider_clients.py`
- Create: `cli/src/modelable/llm/prompting.py`
- Modify: `cli/src/modelable/llm/engine.py`
- Test: `cli/tests/test_llm_provider_client.py`

- [ ] **Step 1: Write tests around request building and response parsing**

```python
def test_request_includes_redacted_workspace_context():
    req = build_llm_request(
        workspace_summary="domain customer { entity Customer @ 1 { email: string } }",
        instruction="make email optional",
        target_ref="customer.Customer@1",
    )
    assert "password" not in req.user
    assert "classification" in req.system

def test_response_parser_extracts_json_object_from_fenced_block():
    parsed = parse_structured_response("```json\n{\"op\":\"update\"}\n```")
    assert parsed["op"] == "update"
```

- [ ] **Step 2: Implement a provider client wrapper**

```python
def complete_with_provider(provider: LLMProvider, request: LLMRequest) -> LLMResponse:
    response = provider.complete(request)
    if not response.content.strip():
        raise ValueError("empty LLM response")
    return response
```

- [ ] **Step 3: Thread the provider through existing assistant entrypoints**

```python
def generate_entity_from_prompt(prompt: str, domain_name: str | None, model_name: str | None, provider: LLMProvider | None):
    if provider is None:
        return fallback_generated_mdl(prompt, domain_name=domain_name, model_name=model_name)
    response = complete_with_provider(provider, request)
    return response.content
```

- [ ] **Step 4: Keep the deterministic fallback path**

```python
if provider is unavailable:
    # Use the current heuristic implementation only as a fallback.
    return local_fallback(prompt, domain_name=domain_name, model_name=model_name)
```

- [ ] **Step 5: Run the focused provider tests**

Run: `uv run pytest tests/test_llm_provider_client.py -v`
Expected: request construction, parsing, and fallback behavior pass.

---

### Task 3: Make update workflows model-driven and structured

**Files:**
- Modify: `cli/src/modelable/commands/llm.py`
- Modify: `cli/src/modelable/llm/engine.py`
- Create: `cli/src/modelable/llm/update_plan.py`
- Test: `cli/tests/test_llm_update_plan.py`

- [ ] **Step 1: Write tests for structured edit plans**

```python
def test_update_plan_extracts_field_changes():
    plan = parse_update_plan('{"target":"customer.Customer@1","changes":[{"kind":"make_optional","field":"email"}]}')
    assert plan.changes[0].field == "email"
```

- [ ] **Step 2: Define the structured update schema**

```python
from pydantic import BaseModel

class UpdateChange(BaseModel):
    kind: str
    field: str
    type: str | None = None
    source: str | None = None

class UpdatePlan(BaseModel):
    target: str
    rationale: str | None = None
    warnings: list[str] = []
    changes: list[UpdateChange]
```

- [ ] **Step 3: Ask the model for a patch plan before rewriting `.mdl`**

```python
def propose_update_plan(provider: LLMProvider, workspace_summary: str, instruction: str) -> UpdatePlan:
    request = LLMRequest(
        system=UPDATE_SYSTEM_PROMPT,
        user=workspace_summary + "\n\nInstruction:\n" + instruction,
        schema=UpdatePlan.model_json_schema(),
    )
    return UpdatePlan.model_validate_json(complete_with_provider(provider, request).content)
```

- [ ] **Step 4: Apply the structured plan to the parsed IR**

```python
def apply_update_plan(mdl: MdlFile, plan: UpdatePlan) -> tuple[MdlFile, list[str]]:
    updated_mdl = mdl
    warnings: list[str] = []
    for change in plan.changes:
        updated_mdl, change_warnings = apply_single_update_change(updated_mdl, plan.target, change)
        warnings.extend(change_warnings)
    return updated_mdl, warnings
```

- [ ] **Step 5: Preserve preview and validation behavior**

```python
if preview:
    print(render_diff(original_text, new_text))
else:
    write_if_valid(new_text)
```

- [ ] **Step 6: Run the update plan tests**

Run: `uv run pytest tests/test_llm_update_plan.py -v`
Expected: structured edits are parsed and applied deterministically.

---

### Task 4: Wire provider-backed flows into the CLI

**Files:**
- Modify: `cli/src/modelable/commands/llm.py`
- Modify: `cli/src/modelable/cli.py`
- Test: `cli/tests/test_llm_features.py`
- Test: `cli/tests/test_cli_help.py`

- [ ] **Step 1: Add CLI flags for provider selection and credentials**

```python
@click.option("--provider", default=None, help="Model provider name, for example openai, anthropic, or local.")
@click.option("--model", default=None, help="Model identifier.")
@click.option("--api-key-env", default=None, help="Environment variable name that contains the provider key.")
```

- [ ] **Step 2: Surface a clean failure when credentials are missing**

```python
raise click.ClickException(
    "LLM provider 'openai' is enabled but no API key was found. Set OPENAI_API_KEY or pass --api-key-env."
)
```

- [ ] **Step 3: Keep the existing local fallback available for preview and offline work**

```python
if provider is None:
    return render_mdl_from_ir(local_fallback_ir)
```

- [ ] **Step 4: Add end-to-end CLI tests with a mocked provider**

```python
def test_update_uses_provider_when_available(monkeypatch):
    provider = DummyProvider("make email optional")
    result = run_update_command(provider=provider, ref="customer.Customer@1", instruction="make email optional")
    assert "email?" in result.content
```

- [ ] **Step 5: Run the CLI tests**

Run: `uv run pytest tests/test_llm_features.py tests/test_cli_help.py -v`
Expected: help text, provider errors, and update routing all pass.

---

### Task 5: Add provider-facing observability and safety checks

**Files:**
- Modify: `cli/src/modelable/llm/redaction.py`
- Modify: `cli/src/modelable/llm/context.py`
- Modify: `cli/src/modelable/llm/render.py`
- Test: `cli/tests/test_llm_redaction.py`
- Test: `cli/tests/test_llm_context.py`

- [ ] **Step 1: Tighten redaction coverage for API prompts**

```python
def test_redaction_masks_tokens_passwords_and_private_keys():
    assert redact("token=abc password=secret PRIVATE KEY") == "token=[REDACTED] password=[REDACTED] PRIVATE KEY=[REDACTED]"
```

- [ ] **Step 2: Add token-budgeted context assembly**

```python
def build_prompt_context(workspace_text: str, target_ref: str, instruction: str, max_chars: int = 12000) -> PromptContext:
    redacted = redact_sensitive_values(workspace_text)
    clipped = redacted[:max_chars]
    return PromptContext(
        system=SYSTEM_PROMPT,
        user=f"Target: {target_ref}\n\nInstruction:\n{instruction}\n\nContext:\n{clipped}",
    )
```

- [ ] **Step 3: Emit provider and model metadata in stdout for writes**

```python
console.print(f"provider={provider} model={model} tokens={usage}")
```

- [ ] **Step 4: Keep prompts reproducible and reviewable**

```python
def render_prompt_snapshot(request: LLMRequest) -> str:
    def render_prompt_snapshot(request: LLMRequest) -> str:
        return request.system + "\n\n" + request.user
```

- [ ] **Step 5: Run the safety tests**

Run: `uv run pytest tests/test_llm_redaction.py tests/test_llm_context.py -v`
Expected: prompts are redacted and bounded.

---

### Task 6: Update docs and acceptance criteria

**Files:**
- Modify: `docs/llm-integration-spec.md`
- Modify: `docs/cli-spec.md`
- Modify: `docs/README.md`
- Modify: `docs/mvp-implementation-plan.md` if the new provider-backed assistant changes rollout expectations

- [ ] **Step 1: Update the LLM integration spec to distinguish provider-backed and fallback modes**

```md
- Provider-backed mode is the primary path for quality.
- Local fallback mode is acceptable for offline preview and deterministic scaffolding.
- All writes still pass parser and validation gates.
```

- [ ] **Step 2: Update the CLI spec for provider flags and missing-key failures**

```md
modelable update <Domain.Model@version> "<edit instruction>" --path PATH [--output FILE] [--preview] [--provider NAME] [--model MODEL] [--api-key-env ENV]
```

- [ ] **Step 3: Add a concise docs index note**

```md
- LLM integration now depends on a provider abstraction with optional local fallback.
```

- [ ] **Step 4: Review the Markdown diff for consistency**

Run: inspect the changed Markdown files and confirm the provider/back-end story is consistent.
Expected: the docs tell one story about provider-backed generation and validation-first writes.

---

### Task 7: End-to-end verification and commit

**Files:**
- No new files expected

- [ ] **Step 1: Run the full CLI test suite**

Run: `uv run pytest tests -q`
Expected: all tests pass with the provider abstraction in place.

- [ ] **Step 2: Run the MVP validation gate**

Run: `uv run modelable validate ../samples/mvp`
Expected: `OK 2 files valid.`

- [ ] **Step 3: Check repo hygiene**

Run: `git status --short`
Expected: only intended source, test, and doc changes are present.

- [ ] **Step 4: Commit the provider integration**

```bash
git add cli/src/modelable/llm cli/src/modelable/commands/llm.py cli/src/modelable/cli.py cli/tests docs
git commit -m "feat: integrate provider-backed LLM workflows"
```

---

### Assumptions
- A real model is required for high-quality natural-language updates; the current heuristic path should remain only as a fallback.
- The first integration should be provider-agnostic so the project can support a hosted API or a local runtime through the same contract.
- The model must never bypass Modelable's parser, semantic validator, compatibility checks, or governance checks.
- Structured outputs are preferred for `update` because freeform prose is too brittle for safe writes.
