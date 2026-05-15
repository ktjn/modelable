# Modelable IDL — Parser, IR, and Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `.mdl` IDL parser, Pydantic IR, and semantic validator — the foundation every emitter and CLI command depends on.

**Architecture:** A Lark EBNF grammar parses `.mdl` files into a parse tree; a Lark `Transformer` converts that tree into typed Pydantic IR objects; a semantic validator enforces domain rules. A thin `Compiler` class orchestrates the pipeline. The CLI `validate` command runs the full pipeline and reports errors.

**Tech Stack:** Python 3.14+, Lark ≥ 1.1 (Earley parser), Pydantic v2, Click ≥ 8.1, pytest ≥ 7.0, Hatchling (build backend), uv (package and environment manager)

**Scope:** Parser + IR + validation only. Emitters (OpenAPI, Avro, SQL, TypeScript), LSP, and LLM commands are separate plans.

---

## File Map

| File | Purpose |
|---|---|
| `cli/pyproject.toml` | Package config, dependencies, entry point |
| `cli/src/modelable/__init__.py` | Package marker |
| `cli/src/modelable/cli.py` | Click entry point + `validate` command |
| `cli/src/modelable/grammar/modelable.lark` | EBNF grammar — canonical language definition |
| `cli/src/modelable/grammar/__init__.py` | Package marker for resource loading |
| `cli/src/modelable/parser/ir.py` | Pydantic IR models + error types |
| `cli/src/modelable/parser/transformer.py` | Lark parse tree → IR |
| `cli/src/modelable/parser/parse.py` | `parse_text()` / `parse_file()` public API |
| `cli/src/modelable/parser/__init__.py` | Re-exports |
| `cli/src/modelable/validation/semantic.py` | Semantic validation rules |
| `cli/src/modelable/validation/__init__.py` | Re-exports |
| `cli/src/modelable/compiler/compiler.py` | `compile()` orchestration |
| `cli/src/modelable/compiler/__init__.py` | Re-exports |
| `cli/tests/conftest.py` | Shared fixtures |
| `cli/tests/fixtures/customer.mdl` | Valid model fixture |
| `cli/tests/fixtures/billing_projection.mdl` | Valid projection fixture |
| `cli/tests/test_grammar.py` | Parse-without-error tests |
| `cli/tests/test_transformer.py` | Parse tree → IR correctness tests |
| `cli/tests/test_semantic.py` | Validation error tests |
| `cli/tests/test_compiler.py` | End-to-end compile tests |
| `cli/tests/test_cli.py` | CLI command tests |

---

## Task 1: Project scaffold

**Files:**
- Create: `cli/pyproject.toml`
- Create: `cli/src/modelable/__init__.py`
- Create: `cli/src/modelable/grammar/__init__.py`
- Create: `cli/src/modelable/parser/__init__.py`
- Create: `cli/src/modelable/validation/__init__.py`
- Create: `cli/src/modelable/compiler/__init__.py`
- Create: `cli/tests/conftest.py`
- Create: `cli/tests/test_grammar.py`

- [x] **Step 1: Create directory structure**

```
cli/
  src/modelable/grammar/
  src/modelable/parser/
  src/modelable/validation/
  src/modelable/compiler/
  tests/fixtures/
```

Run: `mkdir -p cli/src/modelable/grammar cli/src/modelable/parser cli/src/modelable/validation cli/src/modelable/compiler cli/tests/fixtures`

- [x] **Step 2: Write `cli/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "modelable"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    "click>=8.1",
    "lark>=1.1",
    "pydantic>=2.0",
    "rich>=13.0",
    "jsonschema>=4.23",
    "referencing>=0.35",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
]

[project.scripts]
modelable = "modelable.cli:cli"

[tool.hatch.build.targets.wheel]
packages = ["src/modelable"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.coverage.run]
source = ["src/modelable"]
```

Also create `cli/.python-version`:

```
3.14
```

- [x] **Step 3: Write package markers**

`cli/src/modelable/__init__.py`, `cli/src/modelable/grammar/__init__.py`, `cli/src/modelable/parser/__init__.py`, `cli/src/modelable/validation/__init__.py`, `cli/src/modelable/compiler/__init__.py` — all empty files.

- [x] **Step 4: Write `cli/tests/conftest.py`**

```python
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture
def fixture_path():
    return FIXTURES
```

- [x] **Step 5: Write first failing test in `cli/tests/test_grammar.py`**

```python
from modelable.parser.parse import parse_text

def test_import():
    assert parse_text is not None
```

- [x] **Step 6: Install package and verify test fails**

Run from `cli/`: `uv sync --extra dev && uv run pytest tests/test_grammar.py -v`

Expected: `ModuleNotFoundError: No module named 'modelable.parser.parse'`

- [x] **Step 7: Create stub `cli/src/modelable/parser/parse.py`**

```python
def parse_text(text: str):
    raise NotImplementedError
```

- [x] **Step 8: Run test — expect it to pass**

Run: `uv run pytest tests/test_grammar.py::test_import -v`

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add cli/
git commit -m "feat: scaffold modelable CLI package with uv and Hatchling"
```

---

## Task 2: Grammar — domains, models, fields, and types

**Files:**
- Create: `cli/src/modelable/grammar/modelable.lark`
- Modify: `cli/tests/test_grammar.py`

- [x] **Step 1: Write failing parse test**

Add to `cli/tests/test_grammar.py`:

```python
from modelable.parser.parse import parse_text

SIMPLE_MODEL = """
domain customer {
  owner: "customer-platform"
  description: "Customer data."

  entity Customer @ 2 (additive) {
    @key
    customerId: uuid
    @pii
    email?: string
    status: enum(active, blocked, deleted)
    total: decimal(12, 2)
    tags: array<string>
    createdAt: timestamp
  }
}
"""

def test_parse_simple_model():
    parse_text(SIMPLE_MODEL)  # must not raise
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_grammar.py::test_parse_simple_model -v`

Expected: `NotImplementedError`

- [x] **Step 3: Write `cli/src/modelable/grammar/modelable.lark`**

```lark
// Modelable IDL Grammar
// Parser: Earley

start: statement+

statement: domain_decl
         | binding_decl
         | workspace_decl
         | import_domain_stmt
         | consumer_decl

// ── Domain ───────────────────────────────────────────────────────────────────

domain_decl: "domain" IDENT "{" domain_item* "}"

domain_item: owner_attr
           | desc_attr
           | model_decl
           | projection_decl
           | auto_projections_decl
           | generate_block

owner_attr: "owner" ":" ESCAPED_STRING
desc_attr:  "description" ":" ESCAPED_STRING

// ── Model ────────────────────────────────────────────────────────────────────

model_decl: model_kind IDENT "@" INT "(" change_kind ")" "{" field_decl* "}"

model_kind: "entity"    -> mk_entity
          | "aggregate" -> mk_aggregate
          | "event"     -> mk_event
          | "value"     -> mk_value

change_kind: "additive" -> ck_additive
           | "breaking" -> ck_breaking

field_decl: annotation* IDENT "?"? ":" type_expr

annotation: "@key"                                                  -> ann_key
          | "@pii"                                                  -> ann_pii
          | "@classification" "(" ESCAPED_STRING ")"               -> ann_classification
          | "@deprecated" "(" "replacedBy" ":" ESCAPED_STRING ")"  -> ann_deprecated
          | "@owner" "(" ESCAPED_STRING ")"                        -> ann_owner
          | "@server"                                                -> ann_server

// ── Types ────────────────────────────────────────────────────────────────────

type_expr: primitive_type
         | decimal_type
         | array_type
         | map_type
         | ref_type
         | enum_type
         | IDENT          // named value object reference

primitive_type: "string"    -> pt_string
              | "int"       -> pt_int
              | "float"     -> pt_float
              | "bool"      -> pt_bool
              | "uuid"      -> pt_uuid
              | "timestamp" -> pt_timestamp
              | "date"      -> pt_date
              | "time"      -> pt_time
              | "duration"  -> pt_duration
              | "binary"    -> pt_binary

decimal_type: "decimal" "(" INT "," INT ")"
array_type:   "array" "<" type_expr ">"
map_type:     "map" "<" type_expr "," type_expr ">"
ref_type:     "ref" "<" qualified_name ">"
enum_type:    "enum" "(" IDENT ("," IDENT)* ")"

qualified_name: IDENT ("." IDENT)*

// ── Projection (stub — expanded in Task 3) ───────────────────────────────────

projection_decl: "projection" IDENT "@" INT source_clause "{" proj_field* "}"

source_clause: "from" qualified_name "@" version_spec "as" IDENT join_clause* group_clause?

join_clause: "join" qualified_name "@" version_spec "as" IDENT "on" EXPRESSION

group_clause: "group" "by" qualified_field ("," qualified_field)*

version_spec: INT                  -> version_exact
            | ">=" INT "<" INT     -> version_range
            | ">=" INT             -> version_min

proj_field: annotation* IDENT "<-" qualified_field   -> direct_field
          | annotation* IDENT "=" EXPRESSION          -> computed_field

qualified_field: IDENT "." IDENT

EXPRESSION: /[^\n\r{}]+/

// ── Generate ─────────────────────────────────────────────────────────────────

generate_block: "generate" "{" generate_target* "}"

generate_target: target_name ("->" ESCAPED_STRING)?

target_name: "openapi"                  -> tn_openapi
           | "typescript"              -> tn_typescript
           | "avro"                    -> tn_avro
           | "protobuf"               -> tn_protobuf
           | "sql" "(" db_dialect ")" -> tn_sql
           | "jsonschema"             -> tn_jsonschema
           | "asyncapi"               -> tn_asyncapi
           | "docs"                   -> tn_docs

db_dialect: "postgres" -> dd_postgres
          | "mysql"    -> dd_mysql
          | "sqlite"   -> dd_sqlite

// ── Binding ──────────────────────────────────────────────────────────────────

binding_decl: "binding" IDENT "{" binding_attr* "}"

binding_attr: "model"    ":" qualified_name "@" INT  -> ba_model
            | "adapter"  ":" IDENT                   -> ba_adapter
            | "table"    ":" ESCAPED_STRING           -> ba_table
            | "fields"   ":" "{" field_mapping* "}"  -> ba_fields

field_mapping: IDENT "->" IDENT

// ── Workspace ────────────────────────────────────────────────────────────────

workspace_decl: "workspace" ESCAPED_STRING? "{" workspace_item* "}"

workspace_item: generate_block
              | ai_block
              | registry_block
              | peers_list

ai_block: "ai" "{" ai_attr* "}"

ai_attr: "provider" ":" ESCAPED_STRING -> ai_provider
       | "model"    ":" ESCAPED_STRING -> ai_model

auto_projections_decl: "auto" "projections" IDENT "@" INT "{" auto_kind* "}"

auto_kind: "db"
         | "request" auto_filter?
         | "reply" auto_filter?
         | "event" auto_filter?

auto_filter: "exclude" "[" auto_filter_item ("," auto_filter_item)* "]"
           | "on" "[" auto_event_op ("," auto_event_op)* "]"

auto_filter_item: IDENT
                | annotation

auto_event_op: "created"
             | "updated"
             | "deleted"

// ── Import domain ────────────────────────────────────────────────────────────

import_domain_stmt: "import" "domain" IDENT "from" "registry" ESCAPED_STRING
                  | "import" "domain" IDENT "from" "registry" ESCAPED_STRING "at" qualified_name "@" INT "#" IDENT

// ── Consumer (written by CLI, not hand-authored) ─────────────────────────────

consumer_decl: "consumer" "{" consumer_attr* "}"

consumer_attr: "registry"    ":" ESCAPED_STRING
             | "projection" ":" ESCAPED_STRING
             | "uses"       ":" "[" ESCAPED_STRING ("," ESCAPED_STRING)* "]"

// ── Registry block (inside workspace) ─────────────────────────────────────────

registry_block: "registry" "{" registry_attr* "}"

registry_attr: "id"   ":" ESCAPED_STRING
             | "owns" ":" "[" ESCAPED_STRING ("," ESCAPED_STRING)* "]"

peers_list: "peers" ":" "[" peer_entry ("," peer_entry)* "]"

peer_entry: "{" peer_attr* "}"

peer_attr: "id"        ":" ESCAPED_STRING
         | "git"       ":" ESCAPED_STRING
         | "branch"    ":" ESCAPED_STRING
         | "sync"      ":" ESCAPED_STRING
         | "writeback" ":" ESCAPED_STRING

// ── Terminals ────────────────────────────────────────────────────────────────

IDENT: /[a-zA-Z_][a-zA-Z0-9_]*/

%import common.INT
%import common.ESCAPED_STRING
%import common.WS
%ignore WS
%ignore /\/\/[^\n]*/
```

> **Grammar completeness note:** This grammar includes distributed-mode constructs (`@server`, `import domain`, `consumer`, `registry`, `peers`, `auto projections`) that are defined in `idl-design-spec.md` and `distributed-lineage-spec.md`. The initial scaffold (Task 1) need only handle local-mode syntax; distributed constructs may be implemented in a follow-up task once the core parser is stable.

- [x] **Step 4: Implement `parse_text` in `cli/src/modelable/parser/parse.py`**

```python
from __future__ import annotations
from pathlib import Path
import importlib.resources
from lark import Lark, UnexpectedInput

_grammar_text = (
    importlib.resources.files("modelable.grammar")
    .joinpath("modelable.lark")
    .read_text(encoding="utf-8")
)
_parser = Lark(_grammar_text, parser="earley", ambiguity="resolve")


class ParseError(Exception):
    pass


def parse_text(text: str):
    """Parse .mdl text and return a raw Lark tree. Raises ParseError on syntax errors."""
    try:
        return _parser.parse(text)
    except UnexpectedInput as e:
        raise ParseError(str(e)) from e


def parse_file(path: str | Path):
    return parse_text(Path(path).read_text(encoding="utf-8"))
```

- [x] **Step 5: Run test — expect it to pass**

Run: `pytest tests/test_grammar.py::test_parse_simple_model -v`

Expected: PASS

- [x] **Step 6: Add type coverage tests**

Add to `cli/tests/test_grammar.py`:

```python
def test_parse_all_primitive_types():
    parse_text("""
    domain types {
      entity AllTypes @ 1 (additive) {
        a: string
        b: int
        c: float
        d: bool
        e: uuid
        f: timestamp
        g: date
        h: time
        i: duration
        j: binary
      }
    }
    """)

def test_parse_composite_types():
    parse_text("""
    domain types {
      entity Composite @ 1 (additive) {
        @key id: uuid
        tags: array<string>
        meta: map<string, int>
        total: decimal(12, 2)
        addr: ref<address.Address>
        status: enum(active, inactive)
      }
    }
    """)

def test_parse_annotations():
    parse_text("""
    domain types {
      entity Annotated @ 1 (additive) {
        @key id: uuid
        @pii email?: string
        @classification("restricted") secret: string
        @deprecated(replacedBy: "email") oldEmail?: string
        @owner("team-a") managed: string
      }
    }
    """)
```

- [x] **Step 7: Run all grammar tests**

Run: `pytest tests/test_grammar.py -v`

Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add cli/src/modelable/grammar/modelable.lark cli/src/modelable/parser/parse.py cli/tests/test_grammar.py
git commit -m "feat: add Lark grammar for domains, models, fields, and types"
```

---

## Task 3: Grammar — projections and fixture files

**Files:**
- Create: `cli/tests/fixtures/customer.mdl`
- Create: `cli/tests/fixtures/billing_projection.mdl`
- Modify: `cli/tests/test_grammar.py`

The grammar already handles projections (added as a stub in Task 2). This task validates it with real fixture files and adds projection-specific parse tests.

- [x] **Step 1: Write `cli/tests/fixtures/customer.mdl`**

```mdl
domain customer {
  owner: "customer-platform"
  description: "Customer identity and lifecycle."

  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    legalName: string
    createdAt: timestamp
  }

  entity Customer @ 2 (additive) {
    @key
    customerId: uuid
    legalName: string
    @pii
    email?: string
    status: enum(active, blocked, deleted)
    createdAt: timestamp
  }
}
```

- [x] **Step 2: Write `cli/tests/fixtures/billing_projection.mdl`**

```mdl
domain billing {
  owner: "billing-platform"

  projection BillingCustomer @ 1
    from customer.Customer @ 2 as c
  {
    billingCustomerId <- c.customerId
    name <- c.legalName
    @pii
    invoiceEmail <- c.email
    isBillable = c.status == "active"
  }

  projection CustomerOrderStats @ 1
    from orders.Order @ 3 as o
    group by o.customerId
  {
    customerId <- o.customerId
    orderCount = count(o.orderId)
    totalSpent = sum(o.totalAmount)
    lastOrderAt = max(o.createdAt)
  }

  generate {
    openapi -> "./generated/api/"
    typescript -> "./generated/types/"
    sql(postgres) -> "./generated/sql/"
  }
}
```

- [x] **Step 3: Write fixture parse tests**

Add to `cli/tests/test_grammar.py`:

```python
def test_parse_customer_fixture(fixture_path):
    from modelable.parser.parse import parse_file
    parse_file(fixture_path / "customer.mdl")

def test_parse_billing_projection_fixture(fixture_path):
    from modelable.parser.parse import parse_file
    parse_file(fixture_path / "billing_projection.mdl")

def test_parse_direct_mapping():
    parse_text("""
    domain billing {
      projection BillingCustomer @ 1
        from customer.Customer @ 2 as c
      {
        id <- c.customerId
        name <- c.legalName
      }
    }
    """)

def test_parse_join():
    parse_text("""
    domain billing {
      projection OrderLine @ 1
        from orders.Order @ 1 as o
        join customer.Customer @ 2 as c on o.customerId == c.customerId
      {
        orderId <- o.orderId
        customerName <- c.legalName
      }
    }
    """)

def test_parse_version_range():
    parse_text("""
    domain billing {
      projection Ranged @ 1
        from customer.Customer @ >=2 <3 as c
      {
        id <- c.customerId
      }
    }
    """)

def test_parse_aggregation():
    parse_text("""
    domain stats {
      projection OrderStats @ 1
        from orders.Order @ 1 as o
        group by o.customerId
      {
        customerId <- o.customerId
        total = sum(o.amount)
      }
    }
    """)
```

- [x] **Step 4: Run tests**

Run: `pytest tests/test_grammar.py -v`

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add cli/tests/fixtures/ cli/tests/test_grammar.py
git commit -m "feat: add projection grammar tests and MDL fixture files"
```

---

## Task 4: Pydantic IR models

**Files:**
- Create: `cli/src/modelable/parser/ir.py`
- Modify: `cli/src/modelable/parser/__init__.py`
- Create: `cli/tests/test_transformer.py` (failing stub)

- [x] **Step 1: Write failing test**

Create `cli/tests/test_transformer.py`:

```python
from modelable.parser.ir import (
    MdlFile, DomainDef, ModelVersion, ModelKind, ChangeKind,
    FieldDef, PrimitiveType, EnumType, AnnKey, AnnPii,
)

def test_ir_model_construction():
    field = FieldDef(
        name="customerId",
        type=PrimitiveType(kind="uuid"),
        optional=False,
        annotations=[AnnKey()],
    )
    version = ModelVersion(
        model_kind=ModelKind.entity,
        version=2,
        change_kind=ChangeKind.additive,
        fields=[field],
    )
    domain = DomainDef(
        name="customer",
        models={"Customer": [version]},
    )
    mdl = MdlFile(domains=[domain])
    assert mdl.domains[0].name == "customer"
    assert mdl.domains[0].models["Customer"][0].version == 2
    assert mdl.domains[0].models["Customer"][0].fields[0].is_key
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transformer.py::test_ir_model_construction -v`

Expected: `ModuleNotFoundError`

- [x] **Step 3: Write `cli/src/modelable/parser/ir.py`**

```python
from __future__ import annotations
from typing import Literal, Union, Optional, Annotated
from pydantic import BaseModel, Field
from enum import Enum


# ── Errors ────────────────────────────────────────────────────────────────────

class ParseError(Exception):
    pass


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


# ── Annotations ───────────────────────────────────────────────────────────────

class AnnKey(BaseModel):
    kind: Literal["key"] = "key"

class AnnPii(BaseModel):
    kind: Literal["pii"] = "pii"

class AnnClassification(BaseModel):
    kind: Literal["classification"] = "classification"
    level: str

class AnnDeprecated(BaseModel):
    kind: Literal["deprecated"] = "deprecated"
    replaced_by: str

class AnnOwner(BaseModel):
    kind: Literal["owner"] = "owner"
    team: str

Annotation = Annotated[
    Union[AnnKey, AnnPii, AnnClassification, AnnDeprecated, AnnOwner],
    Field(discriminator="kind"),
]


# ── Types ─────────────────────────────────────────────────────────────────────

class PrimitiveType(BaseModel):
    kind: Literal["string", "int", "float", "bool", "uuid",
                  "timestamp", "date", "time", "duration", "binary"]

class DecimalType(BaseModel):
    kind: Literal["decimal"] = "decimal"
    precision: int
    scale: int

class ArrayType(BaseModel):
    kind: Literal["array"] = "array"
    item: FieldType

class MapType(BaseModel):
    kind: Literal["map"] = "map"
    key: FieldType
    value: FieldType

class RefType(BaseModel):
    kind: Literal["ref"] = "ref"
    target: str

class EnumType(BaseModel):
    kind: Literal["enum"] = "enum"
    values: list[str]

class NamedType(BaseModel):
    kind: Literal["named"] = "named"
    name: str

FieldType = Annotated[
    Union[PrimitiveType, DecimalType, ArrayType, MapType, RefType, EnumType, NamedType],
    Field(discriminator="kind"),
]

# Resolve forward references
ArrayType.model_rebuild()
MapType.model_rebuild()


# ── Fields ────────────────────────────────────────────────────────────────────

class FieldDef(BaseModel):
    name: str
    type: FieldType
    optional: bool = False
    annotations: list[Annotation] = []

    @property
    def is_key(self) -> bool:
        return any(a.kind == "key" for a in self.annotations)

    @property
    def is_pii(self) -> bool:
        return any(a.kind == "pii" for a in self.annotations)


# ── Models ────────────────────────────────────────────────────────────────────

class ModelKind(str, Enum):
    entity = "entity"
    aggregate = "aggregate"
    event = "event"
    value = "value"

class ChangeKind(str, Enum):
    additive = "additive"
    breaking = "breaking"

class ModelVersion(BaseModel):
    model_kind: ModelKind
    version: int
    change_kind: ChangeKind
    fields: list[FieldDef]


# ── Projections ───────────────────────────────────────────────────────────────

class VersionExact(BaseModel):
    kind: Literal["exact"] = "exact"
    version: int

class VersionRange(BaseModel):
    kind: Literal["range"] = "range"
    min_inclusive: int
    max_exclusive: int

class VersionMin(BaseModel):
    kind: Literal["min"] = "min"
    min_inclusive: int

VersionSpec = Annotated[
    Union[VersionExact, VersionRange, VersionMin],
    Field(discriminator="kind"),
]

class SourceRef(BaseModel):
    model: str   # "domain.ModelName"
    version: VersionSpec
    alias: str

class JoinRef(BaseModel):
    model: str
    version: VersionSpec
    alias: str
    on: str      # raw expression string

class DirectMapping(BaseModel):
    kind: Literal["direct"] = "direct"
    source_alias: str
    source_field: str

class ComputedMapping(BaseModel):
    kind: Literal["computed"] = "computed"
    expression: str

ProjectionMapping = Annotated[
    Union[DirectMapping, ComputedMapping],
    Field(discriminator="kind"),
]

class ProjectionField(BaseModel):
    name: str
    mapping: ProjectionMapping
    annotations: list[Annotation] = []

    @property
    def is_pii(self) -> bool:
        return any(a.kind == "pii" for a in self.annotations)

class ProjectionVersion(BaseModel):
    version: int
    source: SourceRef
    joins: list[JoinRef] = []
    group_by: list[str] = []   # "alias.field"
    fields: list[ProjectionField]


# ── Generate targets ──────────────────────────────────────────────────────────

class GenerateTarget(BaseModel):
    name: str                  # "openapi", "typescript", "avro", etc.
    dialect: Optional[str] = None   # for sql(postgres)
    output_path: Optional[str] = None

class AiConfig(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None


# ── Bindings ──────────────────────────────────────────────────────────────────

class FieldMapping(BaseModel):
    source: str
    target: str

class BindingDef(BaseModel):
    name: str
    model: str        # "domain.ModelName"
    model_version: int
    adapter: str
    table: Optional[str] = None
    field_mappings: list[FieldMapping] = []


# ── Top-level ─────────────────────────────────────────────────────────────────

class DomainDef(BaseModel):
    name: str
    owner: Optional[str] = None
    description: Optional[str] = None
    models: dict[str, list[ModelVersion]] = {}
    projections: dict[str, list[ProjectionVersion]] = {}
    generate_targets: list[GenerateTarget] = []

class WorkspaceDef(BaseModel):
    generate_targets: list[GenerateTarget] = []
    ai: Optional[AiConfig] = None

class MdlFile(BaseModel):
    domains: list[DomainDef] = []
    bindings: list[BindingDef] = []
    workspace: Optional[WorkspaceDef] = None
```

- [x] **Step 4: Run test — expect it to pass**

Run: `pytest tests/test_transformer.py::test_ir_model_construction -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/src/modelable/parser/ir.py cli/tests/test_transformer.py
git commit -m "feat: add Pydantic IR models for MDL parse tree"
```

---

## Task 5: Transformer — models and fields

**Files:**
- Create: `cli/src/modelable/parser/transformer.py`
- Modify: `cli/src/modelable/parser/parse.py`
- Modify: `cli/tests/test_transformer.py`

- [x] **Step 1: Write failing transformer test**

Add to `cli/tests/test_transformer.py`:

```python
from modelable.parser.parse import parse_text_to_ir

def test_transform_simple_model():
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "customer-platform"
      entity Customer @ 2 (additive) {
        @key
        customerId: uuid
        @pii
        email?: string
        status: enum(active, blocked)
      }
    }
    """)
    assert len(mdl.domains) == 1
    domain = mdl.domains[0]
    assert domain.name == "customer"
    assert domain.owner == "customer-platform"
    versions = domain.models["Customer"]
    assert len(versions) == 1
    v = versions[0]
    assert v.version == 2
    assert v.change_kind.value == "additive"
    assert v.model_kind.value == "entity"
    fields = {f.name: f for f in v.fields}
    assert fields["customerId"].is_key
    assert fields["customerId"].type.kind == "uuid"
    assert fields["email"].is_pii
    assert fields["email"].optional
    assert fields["status"].type.kind == "enum"
    assert fields["status"].type.values == ["active", "blocked"]
```

- [x] **Step 2: Run to verify failure**

Run: `pytest tests/test_transformer.py::test_transform_simple_model -v`

Expected: `AttributeError: module 'modelable.parser.parse' has no attribute 'parse_text_to_ir'`

- [x] **Step 3: Write `cli/src/modelable/parser/transformer.py`**

```python
from __future__ import annotations
from lark import Transformer, Token, Tree
from .ir import (
    MdlFile, DomainDef, ModelVersion, ModelKind, ChangeKind,
    FieldDef, FieldType, Annotation,
    PrimitiveType, DecimalType, ArrayType, MapType, RefType, EnumType, NamedType,
    AnnKey, AnnPii, AnnClassification, AnnDeprecated, AnnOwner,
    ProjectionVersion, ProjectionField, SourceRef, JoinRef,
    DirectMapping, ComputedMapping,
    VersionExact, VersionRange, VersionMin,
    GenerateTarget, BindingDef, FieldMapping, WorkspaceDef,
)


def _str(token) -> str:
    """Extract string value, stripping quotes from ESCAPED_STRING tokens."""
    s = str(token)
    if s.startswith('"') or s.startswith("'"):
        return s[1:-1]
    return s


class MdlTransformer(Transformer):

    # ── Start ──────────────────────────────────────────────────────────────────

    def start(self, items):
        domains, bindings, workspace = [], [], None
        for item in items:
            if isinstance(item, DomainDef):
                domains.append(item)
            elif isinstance(item, BindingDef):
                bindings.append(item)
            elif isinstance(item, WorkspaceDef):
                workspace = item
        return MdlFile(domains=domains, bindings=bindings, workspace=workspace)

    def statement(self, items):
        return items[0]

    # ── Domain ────────────────────────────────────────────────────────────────

    def domain_decl(self, items):
        name = str(items[0])
        owner = description = None
        models: dict[str, list[ModelVersion]] = {}
        projections: dict[str, list[ProjectionVersion]] = {}
        generate_targets = []

        for item in items[1:]:
            if isinstance(item, tuple):
                tag, val = item
                if tag == "owner":
                    owner = val
                elif tag == "description":
                    description = val
                elif tag == "model":
                    mname, mver = val
                    models.setdefault(mname, []).append(mver)
                elif tag == "projection":
                    pname, pver = val
                    projections.setdefault(pname, []).append(pver)
                elif tag == "generate":
                    generate_targets = val

        return DomainDef(
            name=name, owner=owner, description=description,
            models=models, projections=projections,
            generate_targets=generate_targets,
        )

    def domain_item(self, items):
        return items[0]

    def owner_attr(self, items):
        return ("owner", _str(items[0]))

    def desc_attr(self, items):
        return ("description", _str(items[0]))

    # ── Model ─────────────────────────────────────────────────────────────────

    def model_decl(self, items):
        model_kind = items[0]
        name = str(items[1])
        version = int(items[2])
        change_kind = items[3]
        fields = [f for f in items[4:] if isinstance(f, FieldDef)]
        return ("model", name, ModelVersion(
            model_kind=model_kind,
            version=version,
            change_kind=change_kind,
            fields=fields,
        ))

    def mk_entity(self, _):    return ModelKind.entity
    def mk_aggregate(self, _): return ModelKind.aggregate
    def mk_event(self, _):     return ModelKind.event
    def mk_value(self, _):     return ModelKind.value

    def ck_additive(self, _):  return ChangeKind.additive
    def ck_breaking(self, _):  return ChangeKind.breaking

    # ── Fields ────────────────────────────────────────────────────────────────

    def field_decl(self, items):
        annotations = [i for i in items if isinstance(i, (AnnKey, AnnPii, AnnClassification, AnnDeprecated, AnnOwner))]
        rest = [i for i in items if not isinstance(i, (AnnKey, AnnPii, AnnClassification, AnnDeprecated, AnnOwner))]
        # rest contains: IDENT, optional "?" token if present, type_expr
        tokens_and_types = [(type(i).__name__, i) for i in rest]
        name = str(rest[0])
        optional = any(str(i) == "?" for i in rest)
        field_type = rest[-1]  # last non-annotation item is the type
        return FieldDef(name=name, type=field_type, optional=optional, annotations=annotations)

    def ann_key(self, _):        return AnnKey()
    def ann_pii(self, _):        return AnnPii()

    def ann_classification(self, items):
        return AnnClassification(level=_str(items[0]))

    def ann_deprecated(self, items):
        return AnnDeprecated(replaced_by=_str(items[0]))

    def ann_owner(self, items):
        return AnnOwner(team=_str(items[0]))

    def annotation(self, items):
        return items[0]

    # ── Types ─────────────────────────────────────────────────────────────────

    def type_expr(self, items):
        return items[0]

    def pt_string(self, _):    return PrimitiveType(kind="string")
    def pt_int(self, _):       return PrimitiveType(kind="int")
    def pt_float(self, _):     return PrimitiveType(kind="float")
    def pt_bool(self, _):      return PrimitiveType(kind="bool")
    def pt_uuid(self, _):      return PrimitiveType(kind="uuid")
    def pt_timestamp(self, _): return PrimitiveType(kind="timestamp")
    def pt_date(self, _):      return PrimitiveType(kind="date")
    def pt_time(self, _):      return PrimitiveType(kind="time")
    def pt_duration(self, _):  return PrimitiveType(kind="duration")
    def pt_binary(self, _):    return PrimitiveType(kind="binary")
    def primitive_type(self, items): return items[0]

    def decimal_type(self, items):
        return DecimalType(precision=int(items[0]), scale=int(items[1]))

    def array_type(self, items):
        return ArrayType(item=items[0])

    def map_type(self, items):
        return MapType(key=items[0], value=items[1])

    def ref_type(self, items):
        return RefType(target=str(items[0]))

    def enum_type(self, items):
        return EnumType(values=[str(i) for i in items])

    def qualified_name(self, items):
        return ".".join(str(i) for i in items)

    def IDENT(self, token):
        return str(token)

    # When type_expr falls through to bare IDENT (named value object)
    def __default_token__(self, token):
        return token

    # ── Projections ───────────────────────────────────────────────────────────

    def projection_decl(self, items):
        name = str(items[0])
        version = int(items[1])
        source_clause = items[2]
        fields = [f for f in items[3:] if isinstance(f, ProjectionField)]
        source, joins, group_by = source_clause
        return ("projection", name, ProjectionVersion(
            version=version,
            source=source,
            joins=joins,
            group_by=group_by,
            fields=fields,
        ))

    def source_clause(self, items):
        model = str(items[0])
        version = items[1]
        alias = str(items[2])
        joins = [i for i in items[3:] if isinstance(i, JoinRef)]
        group_by_items = [i for i in items[3:] if isinstance(i, list)]
        group_by = group_by_items[0] if group_by_items else []
        return (SourceRef(model=model, version=version, alias=alias), joins, group_by)

    def join_clause(self, items):
        model = str(items[0])
        version = items[1]
        alias = str(items[2])
        on = str(items[3]).strip()
        return JoinRef(model=model, version=version, alias=alias, on=on)

    def group_clause(self, items):
        return [str(i) for i in items]

    def version_spec(self, items):
        return items[0]

    def version_exact(self, items):
        return VersionExact(version=int(items[0]))

    def version_range(self, items):
        return VersionRange(min_inclusive=int(items[0]), max_exclusive=int(items[1]))

    def version_min(self, items):
        return VersionMin(min_inclusive=int(items[0]))

    def qualified_field(self, items):
        return f"{items[0]}.{items[1]}"

    def direct_field(self, items):
        annotations = [i for i in items if isinstance(i, (AnnKey, AnnPii, AnnClassification, AnnDeprecated, AnnOwner))]
        rest = [i for i in items if not isinstance(i, (AnnKey, AnnPii, AnnClassification, AnnDeprecated, AnnOwner))]
        name = str(rest[0])
        source = str(rest[1])   # "alias.field"
        alias, field = source.split(".", 1)
        return ProjectionField(
            name=name,
            mapping=DirectMapping(source_alias=alias, source_field=field),
            annotations=annotations,
        )

    def computed_field(self, items):
        annotations = [i for i in items if isinstance(i, (AnnKey, AnnPii, AnnClassification, AnnDeprecated, AnnOwner))]
        rest = [i for i in items if not isinstance(i, (AnnKey, AnnPii, AnnClassification, AnnDeprecated, AnnOwner))]
        name = str(rest[0])
        expression = str(rest[1]).strip()
        return ProjectionField(
            name=name,
            mapping=ComputedMapping(expression=expression),
            annotations=annotations,
        )

    def proj_field(self, items):
        return items[0]

    # ── Generate ──────────────────────────────────────────────────────────────

    def generate_block(self, items):
        return ("generate", [i for i in items if isinstance(i, GenerateTarget)])

    def generate_target(self, items):
        name_item = items[0]
        output_path = _str(items[1]) if len(items) > 1 else None
        if isinstance(name_item, tuple):
            name, dialect = name_item
        else:
            name, dialect = name_item, None
        return GenerateTarget(name=name, dialect=dialect, output_path=output_path)

    def tn_openapi(self, _):     return "openapi"
    def tn_typescript(self, _):  return "typescript"
    def tn_avro(self, _):        return "avro"
    def tn_protobuf(self, _):    return "protobuf"
    def tn_sql(self, items):     return ("sql", str(items[0]))
    def tn_jsonschema(self, _):  return "jsonschema"
    def tn_asyncapi(self, _):    return "asyncapi"
    def tn_docs(self, _):        return "docs"
    def target_name(self, items): return items[0]

    def dd_postgres(self, _): return "postgres"
    def dd_mysql(self, _):    return "mysql"
    def dd_sqlite(self, _):   return "sqlite"
    def db_dialect(self, items): return items[0]

    # ── Binding ───────────────────────────────────────────────────────────────

    def binding_decl(self, items):
        name = str(items[0])
        model = model_version = adapter = table = None
        field_mappings = []
        for item in items[1:]:
            if isinstance(item, tuple):
                tag, val = item
                if tag == "model":
                    model, model_version = val
                elif tag == "adapter":
                    adapter = val
                elif tag == "table":
                    table = val
                elif tag == "fields":
                    field_mappings = val
        return BindingDef(
            name=name, model=model, model_version=model_version,
            adapter=adapter, table=table, field_mappings=field_mappings,
        )

    def ba_model(self, items):
        return ("model", (str(items[0]), int(items[1])))

    def ba_adapter(self, items):
        return ("adapter", str(items[0]))

    def ba_table(self, items):
        return ("table", _str(items[0]))

    def ba_fields(self, items):
        return ("fields", [i for i in items if isinstance(i, FieldMapping)])

    def field_mapping(self, items):
        return FieldMapping(source=str(items[0]), target=str(items[1]))

    def binding_attr(self, items):
        return items[0]

    # ── Workspace ─────────────────────────────────────────────────────────────

    def ai_provider(self, items):
        return ("provider", _str(items[0]))

    def ai_model(self, items):
        return ("model", _str(items[0]))

    def ai_attr(self, items):
        return items[0]

    def ai_block(self, items):
        attrs = dict(items)
        return ("ai", AiConfig(
            provider=attrs.get("provider"),
            model=attrs.get("model"),
        ))

    def workspace_decl(self, items):
        generate_targets = []
        ai = None
        for item in items:
            if isinstance(item, tuple) and item[0] == "generate":
                generate_targets = item[1]
            elif isinstance(item, tuple) and item[0] == "ai":
                ai = item[1]
        return WorkspaceDef(generate_targets=generate_targets, ai=ai)
```

- [x] **Step 4: Add `parse_text_to_ir` to `cli/src/modelable/parser/parse.py`**

```python
from .transformer import MdlTransformer
from .ir import MdlFile, ParseError as IrParseError

def parse_text_to_ir(text: str) -> MdlFile:
    """Parse .mdl text and return typed IR. Raises ParseError on syntax errors."""
    tree = parse_text(text)
    return MdlTransformer().transform(tree)

def parse_file_to_ir(path) -> MdlFile:
    return parse_text_to_ir(Path(path).read_text(encoding="utf-8"))
```

- [x] **Step 5: Run test — expect it to pass**

Run: `pytest tests/test_transformer.py::test_transform_simple_model -v`

Expected: PASS

- [x] **Step 6: Add projection transformer test**

Add to `cli/tests/test_transformer.py`:

```python
def test_transform_projection():
    mdl = parse_text_to_ir("""
    domain billing {
      projection BillingCustomer @ 1
        from customer.Customer @ 2 as c
      {
        billingCustomerId <- c.customerId
        isBillable = c.status == "active"
      }
    }
    """)
    domain = mdl.domains[0]
    versions = domain.projections["BillingCustomer"]
    assert len(versions) == 1
    pv = versions[0]
    assert pv.version == 1
    assert pv.source.model == "customer.Customer"
    assert pv.source.alias == "c"
    assert pv.source.version.kind == "exact"
    assert pv.source.version.version == 2
    fields = {f.name: f for f in pv.fields}
    assert fields["billingCustomerId"].mapping.kind == "direct"
    assert fields["billingCustomerId"].mapping.source_alias == "c"
    assert fields["billingCustomerId"].mapping.source_field == "customerId"
    assert fields["isBillable"].mapping.kind == "computed"
    assert "c.status" in fields["isBillable"].mapping.expression

def test_transform_version_range():
    mdl = parse_text_to_ir("""
    domain billing {
      projection Ranged @ 1
        from customer.Customer @ >=2 <4 as c
      {
        id <- c.customerId
      }
    }
    """)
    pv = mdl.domains[0].projections["Ranged"][0]
    assert pv.source.version.kind == "range"
    assert pv.source.version.min_inclusive == 2
    assert pv.source.version.max_exclusive == 4

def test_transform_fixture_files(fixture_path):
    from modelable.parser.parse import parse_file_to_ir
    customer_mdl = parse_file_to_ir(fixture_path / "customer.mdl")
    assert customer_mdl.domains[0].name == "customer"
    billing_mdl = parse_file_to_ir(fixture_path / "billing_projection.mdl")
    assert "BillingCustomer" in billing_mdl.domains[0].projections
```

- [x] **Step 7: Run all transformer tests**

Run: `pytest tests/test_transformer.py -v`

Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add cli/src/modelable/parser/transformer.py cli/src/modelable/parser/parse.py cli/tests/test_transformer.py
git commit -m "feat: add Lark transformer converting MDL parse tree to Pydantic IR"
```

---

## Task 6: Semantic validation

**Files:**
- Create: `cli/src/modelable/validation/semantic.py`
- Modify: `cli/src/modelable/validation/__init__.py`
- Create: `cli/tests/test_semantic.py`

Rules to enforce:
1. `entity` and `aggregate` models must have exactly one `@key` field.
2. `event` and `value` models must have no `@key` field.
3. Each model's versions must be in strictly ascending order.
4. Each projection field must have exactly one mapping (`<-` or `=`).
5. Aggregation functions (`count`, `sum`, `min`, `max`, `avg`) may only appear in projections with `group by`.

- [x] **Step 1: Write failing validation tests**

Create `cli/tests/test_semantic.py`:

```python
import pytest
from modelable.parser.parse import parse_text_to_ir
from modelable.validation.semantic import validate
from modelable.parser.ir import ValidationError


def test_valid_entity_passes():
    mdl = parse_text_to_ir("""
    domain customer {
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
    }
    """)
    errors = validate(mdl)
    assert errors == []


def test_entity_missing_key_fails():
    mdl = parse_text_to_ir("""
    domain customer {
      entity Customer @ 1 (additive) {
        customerId: uuid
        name: string
      }
    }
    """)
    errors = validate(mdl)
    assert any("key" in e.lower() for e in errors)


def test_event_must_not_have_key():
    mdl = parse_text_to_ir("""
    domain orders {
      event OrderPlaced @ 1 (additive) {
        @key orderId: uuid
        amount: decimal(10, 2)
      }
    }
    """)
    errors = validate(mdl)
    assert any("key" in e.lower() for e in errors)


def test_versions_must_be_ascending():
    mdl = parse_text_to_ir("""
    domain customer {
      entity Customer @ 2 (additive) {
        @key customerId: uuid
      }
      entity Customer @ 1 (additive) {
        @key customerId: uuid
      }
    }
    """)
    errors = validate(mdl)
    assert any("version" in e.lower() for e in errors)


def test_aggregate_function_without_group_by_fails():
    mdl = parse_text_to_ir("""
    domain stats {
      projection BadStats @ 1
        from orders.Order @ 1 as o
      {
        total = sum(o.amount)
      }
    }
    """)
    errors = validate(mdl)
    assert any("group by" in e.lower() or "aggregat" in e.lower() for e in errors)


def test_aggregate_function_with_group_by_passes():
    mdl = parse_text_to_ir("""
    domain stats {
      projection GoodStats @ 1
        from orders.Order @ 1 as o
        group by o.customerId
      {
        customerId <- o.customerId
        total = sum(o.amount)
      }
    }
    """)
    errors = validate(mdl)
    assert errors == []
```

- [x] **Step 2: Run to verify failures**

Run: `pytest tests/test_semantic.py -v`

Expected: All fail with `ModuleNotFoundError`

- [x] **Step 3: Write `cli/src/modelable/validation/semantic.py`**

```python
from __future__ import annotations
import re
from modelable.parser.ir import MdlFile, ModelKind, ComputedMapping

_AGGREGATE_FUNCTIONS = {"count", "sum", "min", "max", "avg"}
_AGGREGATE_PATTERN = re.compile(
    r'\b(' + '|'.join(_AGGREGATE_FUNCTIONS) + r')\s*\(', re.IGNORECASE
)


def validate(mdl: MdlFile) -> list[str]:
    """Return a list of semantic error strings. Empty list means valid."""
    errors: list[str] = []
    for domain in mdl.domains:
        _validate_models(domain.name, domain.models, errors)
        _validate_projections(domain.name, domain.projections, errors)
    return errors


def _validate_models(domain_name, models, errors):
    for model_name, versions in models.items():
        fqn = f"{domain_name}.{model_name}"

        # Versions must be strictly ascending
        version_nums = [v.version for v in versions]
        for i in range(1, len(version_nums)):
            if version_nums[i] <= version_nums[i - 1]:
                errors.append(
                    f"{fqn}: versions must be strictly ascending, "
                    f"but found {version_nums[i - 1]} followed by {version_nums[i]}"
                )

        for ver in versions:
            key_fields = [f for f in ver.fields if f.is_key]
            if ver.model_kind in (ModelKind.entity, ModelKind.aggregate):
                if len(key_fields) == 0:
                    errors.append(
                        f"{fqn}@{ver.version}: {ver.model_kind.value} must have "
                        f"exactly one @key field"
                    )
                elif len(key_fields) > 1:
                    errors.append(
                        f"{fqn}@{ver.version}: {ver.model_kind.value} has multiple "
                        f"@key fields — use a composite key instead"
                    )
            elif ver.model_kind in (ModelKind.event, ModelKind.value):
                if key_fields:
                    errors.append(
                        f"{fqn}@{ver.version}: {ver.model_kind.value} must not have "
                        f"an @key field"
                    )


def _validate_projections(domain_name, projections, errors):
    for proj_name, versions in projections.items():
        fqn = f"{domain_name}.{proj_name}"
        for pver in versions:
            has_group_by = bool(pver.group_by)
            for field in pver.fields:
                if isinstance(field.mapping, ComputedMapping):
                    expr = field.mapping.expression
                    agg_match = _AGGREGATE_PATTERN.search(expr)
                    if agg_match and not has_group_by:
                        errors.append(
                            f"{fqn}@{pver.version}: field '{field.name}' uses "
                            f"aggregation function '{agg_match.group(1)}' but the "
                            f"projection has no 'group by' clause"
                        )
```

- [x] **Step 4: Run tests**

Run: `pytest tests/test_semantic.py -v`

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add cli/src/modelable/validation/semantic.py cli/tests/test_semantic.py
git commit -m "feat: add semantic validation for models and projections"
```

---

## Task 7: Compiler orchestration and CLI validate command

**Files:**
- Create: `cli/src/modelable/compiler/compiler.py`
- Create: `cli/src/modelable/cli.py`
- Create: `cli/tests/test_compiler.py`
- Create: `cli/tests/test_cli.py`

- [x] **Step 1: Write failing compiler test**

Create `cli/tests/test_compiler.py`:

```python
from modelable.compiler.compiler import compile_text, compile_file

def test_compile_valid_model():
    mdl, errors = compile_text("""
    domain customer {
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
    }
    """)
    assert errors == []
    assert mdl.domains[0].name == "customer"

def test_compile_returns_errors_not_raises():
    mdl, errors = compile_text("""
    domain customer {
      entity Customer @ 1 (additive) {
        customerId: uuid
      }
    }
    """)
    assert len(errors) > 0
    assert any("key" in e.lower() for e in errors)

def test_compile_parse_error_raises():
    from modelable.parser.ir import ParseError
    import pytest
    with pytest.raises(ParseError):
        compile_text("domain { broken yaml }")
```

- [x] **Step 2: Run to verify failures**

Run: `pytest tests/test_compiler.py -v`

Expected: `ModuleNotFoundError`

- [x] **Step 3: Write `cli/src/modelable/compiler/compiler.py`**

```python
from __future__ import annotations
from pathlib import Path
from modelable.parser.parse import parse_text_to_ir, parse_file_to_ir
from modelable.parser.ir import MdlFile
from modelable.validation.semantic import validate


def compile_text(text: str) -> tuple[MdlFile, list[str]]:
    """Parse and validate .mdl text. Returns (ir, errors). Raises ParseError on syntax failure."""
    mdl = parse_text_to_ir(text)
    errors = validate(mdl)
    return mdl, errors


def compile_file(path: str | Path) -> tuple[MdlFile, list[str]]:
    mdl = parse_file_to_ir(path)
    errors = validate(mdl)
    return mdl, errors
```

- [x] **Step 4: Run compiler tests**

Run: `pytest tests/test_compiler.py -v`

Expected: All PASS

- [x] **Step 5: Write failing CLI test**

Create `cli/tests/test_cli.py`:

```python
from click.testing import CliRunner
from modelable.cli import cli

def test_validate_valid_file(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text("""
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""")
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(mdl)])
    assert result.exit_code == 0
    assert "valid" in result.output.lower() or result.output.strip() == ""

def test_validate_invalid_file_exits_nonzero(tmp_path):
    mdl = tmp_path / "bad.mdl"
    mdl.write_text("""
domain customer {
  entity Customer @ 1 (additive) {
    customerId: uuid
  }
}
""")
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(mdl)])
    assert result.exit_code != 0

def test_validate_strict_mode_exits_on_warning(tmp_path):
    """--strict exits non-zero on any error."""
    mdl = tmp_path / "bad.mdl"
    mdl.write_text("""
domain customer {
  entity Customer @ 1 (additive) {
    customerId: uuid
  }
}
""")
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(mdl), "--strict"])
    assert result.exit_code != 0
```

- [x] **Step 6: Run CLI test to verify failure**

Run: `pytest tests/test_cli.py -v`

Expected: `ModuleNotFoundError: No module named 'modelable.cli'`

- [x] **Step 7: Write `cli/src/modelable/cli.py`**

```python
import sys
from pathlib import Path
import click
from rich.console import Console
from rich.text import Text

console = Console()


@click.group()
def cli():
    """Modelable — domain-owned data model compiler."""
    pass


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Exit non-zero on any validation error.")
def validate(path: str, strict: bool):
    """Validate Modelable definition files at PATH (file or directory)."""
    from modelable.compiler.compiler import compile_text, compile_file
    from modelable.parser.ir import ParseError as MdlParseError

    target = Path(path)
    files = [target] if target.is_file() else sorted(target.rglob("*.mdl"))

    if not files:
        console.print("[yellow]No .mdl files found.[/yellow]")
        sys.exit(0)

    total_errors: list[tuple[Path, str]] = []

    for mdl_file in files:
        try:
            _, errors = compile_file(mdl_file)
            for err in errors:
                total_errors.append((mdl_file, err))
        except MdlParseError as e:
            total_errors.append((mdl_file, f"Syntax error: {e}"))

    if total_errors:
        for file, err in total_errors:
            console.print(f"[red]ERROR[/red] {file}: {err}")
        sys.exit(1)
    else:
        if len(files) == 1:
            console.print(f"[green]✓[/green] {files[0]} is valid.")
        else:
            console.print(f"[green]✓[/green] {len(files)} files valid.")
        sys.exit(0)
```

- [x] **Step 8: Run all tests**

Run: `pytest tests/ -v`

Expected: All PASS

- [x] **Step 9: Smoke test the CLI**

```bash
cd cli
echo 'domain customer { entity Customer @ 1 (additive) { @key customerId: uuid } }' > /tmp/test.mdl
modelable validate /tmp/test.mdl
```

Expected output: `✓ /tmp/test.mdl is valid.`

- [ ] **Step 10: Commit**

```bash
git add cli/src/modelable/compiler/ cli/src/modelable/cli.py cli/tests/test_compiler.py cli/tests/test_cli.py
git commit -m "feat: add compiler orchestration and CLI validate command"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| Domain definition (owner, description) | Tasks 2, 5 |
| Model kinds (entity, aggregate, event, value) | Tasks 2, 5, 6 |
| Field types (all primitives, decimal, array, map, ref, enum) | Tasks 2, 5 |
| Field annotations (@key, @pii, @classification, @deprecated, @owner) | Tasks 2, 5 |
| Versioning with changeKind (additive/breaking) | Tasks 2, 5 |
| Projections — direct mapping (`<-`) | Tasks 3, 5 |
| Projections — computed mapping (`=`) | Tasks 3, 5 |
| Projections — joins | Tasks 3, 5 |
| Projections — aggregations with group by | Tasks 3, 5, 6 |
| Version ranges (>=2 <3) | Tasks 2, 5 |
| Generate blocks | Tasks 2, 5 |
| Adapter bindings | Tasks 2, 5 |
| Workspace declaration | Tasks 2, 5 |
| Semantic: entity/aggregate must have @key | Task 6 |
| Semantic: event/value must not have @key | Task 6 |
| Semantic: versions ascending | Task 6 |
| Semantic: aggregation requires group by | Task 6 |
| CLI validate command | Task 7 |

**Not in this plan (separate plans):** Emitters, LSP, LLM commands, `compile` CLI command, `diff`, `lineage`, `docs` commands.
