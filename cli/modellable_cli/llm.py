"""Anthropic SDK integration for LLM-powered describe and generate commands."""

from __future__ import annotations

import os
from typing import Any

import anthropic

MODEL = "claude-opus-4-7"

# System prompt explaining the Modellable DSL. This content is eligible for
# prompt caching — it is large and reused across every LLM call in the session.
_SYSTEM_PROMPT = """\
You are an expert in the Modellable data governance framework. Modellable is a \
meta-model framework for defining, tracing, and governing domain-owned data models \
across disparate systems. It acts as a semantic layer ensuring every data property \
can be traced back to the domain and canonical model that owns it.

## Core Concepts

### Domain
An ownership boundary for models. Fields: `domain` (id), `owner`, `description`, \
`contact`, `policies`.

### Model
A canonical business entity, event, value_object, or aggregate owned by a domain.
- Required: `domain`, `model` (name), `kind`, `version`, `status`, `fields`
- `identity.key` for addressable entities/aggregates

### Projection
A derived versioned contract based on source models. Used for consumer-specific \
read models, analytics, API contracts, stream subscriptions, and materialised replicas.
- Required: `domain`, `projection` (name), `version`, `sources`, `fields`
- Each field must have either `from: alias.fieldName` or `expression: "CEL expr"`
- Optional: `filter`, `groupBy`, `materialisation`, `subscription`, `access`

### Adapter Binding
Connects a projection or model to a concrete backend system.
- Required: `binding` (name), `adapter`, `role` (sink|stream|source), `config`

## Platform Types
- **data-warehouse**: ClickHouse, Snowflake, BigQuery — analytics/OLAP; use \
`append`, `upsert`, or `overwrite_partition` materialisation strategies.
- **high-performance-service**: Redis, MongoDB, Cassandra — sub-10ms reads; use \
`upsert` with TTL; denormalize joins at write time.
- **event-driven-microservices**: Kafka, NATS, Pulsar — async choreography; use \
`subscription` with CEL filter; no materialisation target.
- **ml-feature-store**: Feast, Redis, DuckDB, S3 — PIT-correct features; use \
`snapshot` (offline) and `upsert` (online) with `pitCutoff` join parameters.
- **api-consumer**: OpenAPI 3.1, TypeScript, Protobuf — versioned external contracts; \
use `access.visibility`, `artifacts` list, runtime filter `runtimeParams`.
- **audit-compliance**: S3 WORM, PostgreSQL, immudb — immutable history; use \
`append` or `snapshot` with `immutable: true`, `retentionYears`, `auditLog: true`.

## Field Types
string, boolean, integer, decimal, float, timestamp, date, time, duration, uuid, \
binary, enum, array, object, map, reference

## Classifications
public, internal, confidential, pii, sensitive, restricted

## Materialisation Strategies
append, upsert, snapshot, overwrite_partition

## YAML Format (multi-document, separated by ---)

### Domain
```yaml
domain: customer
owner: customer-platform-team
contact: customer@example.com
description: Customer identity and lifecycle data.
policies:
  defaultClassification: internal
  piiHandling: pseudonymise_before_export
```

### Model
```yaml
domain: customer
model: Customer
kind: entity
version: 3
status: published
identity:
  key: customerId
fields:
  customerId:
    type: uuid
    required: true
  email:
    type: string
    format: email
    classification: pii
    required: true
  status:
    type: enum
    values: [active, suspended, deleted]
    required: true
  createdAt:
    type: timestamp
    required: true
```

### Projection (analytics)
```yaml
domain: analytics
projection: CustomerLifetimeValue
version: 1
status: published
sources:
  - domain: customer
    model: Customer
    version: 3
    alias: c
  - domain: commerce
    model: Order
    version: 2
    alias: o
    joinOn:
      left: c.customerId
      right: o.customerId
    joinType: left
fields:
  customerId:
    from: c.customerId
  emailHash:
    expression: "hmac_sha256(c.email, env.PII_HMAC_SECRET)"
    type: string
  orderCount:
    expression: "count(o.orderId)"
    type: integer
groupBy:
  - c.customerId
  - c.email
materialisation:
  strategy: upsert
  key: customerId
  binding: clickhouse-sink
```

### Projection (streaming subscription)
```yaml
domain: payments
projection: OrderPaymentTriggers
version: 1
sources:
  - domain: commerce
    model: Order
    version: 2
    alias: ord
filter:
  expression: "ord.status == 'confirmed'"
fields:
  orderId:
    from: ord.orderId
  totalAmountCents:
    from: ord.totalAmountCents
subscription:
  source: commerce.order.v2
  adapter: kafka-main
  consumerGroup: payments-order-sub
  deadLetterTopic: payments-order-sub.dlq
```

### Binding
```yaml
binding: redis-customer-profiles
adapter: redis
role: sink
config:
  host: redis.internal
  port: 6380
  tls: true
  keyPrefix: "customer:"
  serialisation: msgpack
  defaultTtlSeconds: 3600
```

## Artifact Formats (for projections with `artifacts:` list)

Each artifact entry requires `format` (one of the IDs below) and `outputPath`.

### API Specification
| Format ID      | Name            | Extension |
|---------------|-----------------|-----------|
| openapi_3_1   | OpenAPI 3.1     | .yaml     |
| openapi_3_0   | OpenAPI 3.0     | .yaml     |
| json_schema   | JSON Schema     | .json     |
| graphql       | GraphQL SDL     | .graphql  |
| asyncapi_3    | AsyncAPI 3      | .yaml     |
| grpc          | gRPC (proto3)   | .proto    |

### Typed Programming Language
| Format ID          | Name                    | Extension |
|-------------------|-------------------------|-----------|
| typescript        | TypeScript              | .d.ts     |
| javascript        | JavaScript (JSDoc)      | .js       |
| python_pydantic   | Python (Pydantic v2)    | .py       |
| python_dataclass  | Python (dataclass)      | .py       |
| go                | Go                      | .go       |
| java              | Java                    | .java     |
| kotlin            | Kotlin                  | .kt       |
| rust              | Rust                    | .rs       |
| csharp            | C#                      | .cs       |
| swift             | Swift                   | .swift    |
| scala             | Scala                   | .scala    |
| ruby              | Ruby                    | .rb       |
| php               | PHP                     | .php      |
| dart              | Dart / Flutter          | .dart     |
| elixir            | Elixir                  | .ex       |

### Binary Serialization
| Format ID       | Name                    | Extension |
|----------------|-------------------------|-----------|
| protobuf       | Protocol Buffers (proto3)| .proto   |
| avro           | Apache Avro             | .avsc     |
| thrift         | Apache Thrift           | .thrift   |
| flatbuffers    | FlatBuffers             | .fbs      |
| capnproto      | Cap'n Proto             | .capnp    |
| msgpack_schema | MessagePack (schema)    | .yaml     |

### SQL / DDL
| Format ID         | Name                  | Extension |
|------------------|-----------------------|-----------|
| sql_postgresql   | SQL — PostgreSQL      | .sql      |
| sql_mysql        | SQL — MySQL/MariaDB   | .sql      |
| sql_clickhouse   | SQL — ClickHouse      | .sql      |
| sql_snowflake    | SQL — Snowflake       | .sql      |
| sql_bigquery     | SQL — BigQuery        | .sql      |
| sql_sqlite       | SQL — SQLite          | .sql      |

### Data Tool / Infrastructure
| Format ID      | Name                       | Extension |
|---------------|----------------------------|-----------|
| dbt           | dbt (schema.yml)           | .yml      |
| terraform     | Terraform (HCL schema)     | .tf       |
| markdown_docs | Markdown Documentation     | .md       |

### Example projection with artifacts
```yaml
domain: marketplace-api
projection: PartnerProductCatalog
version: 1
status: published
sources:
  - domain: catalogue
    model: ProductListing
    version: 3
    alias: pl
fields:
  product_id:
    from: pl.productId
  name:
    from: pl.name
artifacts:
  - format: openapi_3_1
    outputPath: artifacts/openapi/partner-product-catalog-v1.yaml
  - format: typescript
    outputPath: artifacts/typescript/partner-product-catalog-v1.d.ts
  - format: python_pydantic
    outputPath: artifacts/python/partner_product_catalog_v1.py
  - format: protobuf
    outputPath: artifacts/proto/partner_product_catalog_v1.proto
    packageName: marketplace.api.v1
  - format: sql_postgresql
    outputPath: artifacts/sql/partner_product_catalog_v1.sql
```

## Key Rules
1. Published model/projection versions are immutable — incompatible changes need a new version.
2. PII fields must not reach sinks that do not declare a masking/pseudonymisation policy.
3. Adapter-specific config belongs in bindings, not in model or projection definitions.
4. Every derived field in a projection must trace back to a source field via `from` or `expression`.
5. CEL expressions must be deterministic and side-effect-free.
6. Cross-domain data access goes through projections, never direct model references.
7. When generating artifacts for a projection, choose formats appropriate to the platform type:
   - api-consumer: prefer openapi_3_1, typescript, protobuf, json_schema
   - event-driven-microservices: prefer avro, protobuf, asyncapi_3
   - ml-feature-store: prefer python_pydantic, sql_bigquery, sql_snowflake, dbt
   - data-warehouse: prefer sql_clickhouse, sql_snowflake, sql_bigquery, dbt
   - high-performance-service: prefer protobuf, typescript, python_pydantic
   - audit-compliance: prefer sql_postgresql, json_schema, markdown_docs
"""


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it to use LLM features."
        )
    return anthropic.Anthropic(api_key=api_key)


def describe_definitions(yaml_content: str) -> str:
    """
    Ask Claude to explain a set of Modellable YAML definitions in plain English.
    Returns the explanation as a string.
    """
    client = _client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    "Please explain the following Modellable definitions in plain English. "
                    "Describe what this scenario does, what problem it solves, which domains "
                    "are involved, what each projection does, and any notable design decisions "
                    "(e.g. why PIT joins, why specific materialisation strategies, etc.).\n\n"
                    "Be concrete and practical — explain it as you would to a new engineer "
                    "joining the team who needs to understand the data flow.\n\n"
                    f"```yaml\n{yaml_content}\n```"
                ),
            }
        ],
    )
    return response.content[0].text


def generate_definitions(
    description: str,
    platform: str | None = None,
    existing_context: str | None = None,
) -> str:
    """
    Ask Claude to generate Modellable YAML definitions from a natural language description.
    Returns the generated YAML as a string.
    """
    client = _client()

    platform_hint = ""
    if platform:
        platform_hint = f"\n\nTarget platform type: **{platform}**"

    context_hint = ""
    if existing_context:
        context_hint = (
            f"\n\nExisting definitions to build on or integrate with:\n"
            f"```yaml\n{existing_context}\n```"
        )

    user_message = (
        "Generate complete Modellable YAML definitions for the following scenario. "
        "Include domain definitions, model definitions with realistic fields, "
        "projection definitions that demonstrate the platform's key patterns, "
        "and adapter binding configurations.\n\n"
        "Use multi-document YAML (--- separated). Start with a `scenario:` metadata "
        "document, then domains, then models, then projections, then bindings.\n\n"
        "Make the definitions realistic and production-quality: include appropriate "
        "PII classifications, sensible field types, CEL expressions for computed fields, "
        "and binding configs with realistic parameters.\n\n"
        f"Scenario description:\n{description}"
        f"{platform_hint}"
        f"{context_hint}\n\n"
        "Return only the YAML — no prose explanation before or after."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )
    text = response.content[0].text.strip()
    # Strip markdown code fences if the model wrapped the output
    if text.startswith("```yaml"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def suggest_platform(description: str) -> str:
    """
    Ask Claude which platform type best fits a described use case.
    Returns a short recommendation with reasoning.
    """
    client = _client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    "Based on the following use case description, recommend the most "
                    "appropriate Modellable platform type and explain why in 2-3 sentences. "
                    "Also note if multiple platform types apply.\n\n"
                    f"Use case: {description}\n\n"
                    "Platform types to choose from: data-warehouse, high-performance-service, "
                    "event-driven-microservices, ml-feature-store, api-consumer, audit-compliance"
                ),
            }
        ],
    )
    return response.content[0].text
