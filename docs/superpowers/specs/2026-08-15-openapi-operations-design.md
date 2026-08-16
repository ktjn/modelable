# OpenAPI Phase B: Paths and Operations Design

## Status

Proposed design for review. This document is the prerequisite for implementing
the next OpenAPI roadmap slice; it does not change the Modelable grammar or
compiler.

## 1. Purpose

Phase A emits deterministic OpenAPI 3.1 `components.schemas` from API-facing
projections ([Phase A design](archived/2026-08-14-openapi-emission-design.md)).
Phase B adds the missing REST contract surface: paths, HTTP
methods, request bindings, response status codes, and operation metadata.

The `.mdl` source remains the source of truth. Routes must be explicit and
compiler-validated; they must not be inferred from entity names or English
pluralization.

## 2. Goals

- Declare versioned REST operations in `.mdl`.
- Bind each operation explicitly to a path, HTTP method, request projection,
  and one or more response projections.
- Generate valid OpenAPI 3.1 `paths` entries while reusing Phase A schema
  component identifiers.
- Validate path templates, projection versions, status codes, duplicate
  operation identities, and request/reply projection kinds before emission.
- Preserve deterministic output and operation metadata through namespaced
  `x-modelable` extensions.
- Make operation additions, removals, and renames visible to compatibility
  tooling as API-contract changes.

## 3. Non-goals for the first Phase B slice

- OpenAPI import hardening (Phase C).
- Security schemes, OAuth scopes, API keys, mTLS, or global security policy.
- Webhooks, callbacks, links, and server variables.
- Query/header/cookie parameters and multipart or form bodies.
- Automatic CRUD route generation or pluralization.
- Introducing a second route-mapping YAML/JSON source of truth.
- Constraint, nullability, named-enum, or discriminated-union fidelity work
  gated on D1-D4.
- Runtime handlers, routing, authentication, or server implementation.

Query and header parameters may be added in a later grammar extension once a
concrete consumer requires them. The first slice supports path parameters and a
single JSON request body, which covers the contract needed by the current
projection model without inventing a general HTTP parameter type system.

## 4. Proposed grammar

An API declaration lives inside a domain and is bound to one model version.
Its version identifies the reviewed API contract for that model.

```mdl
domain Billing {
  entity Customer @ 1 (additive) {
    @key id: uuid
    name: string
  }

  auto projections Customer @ 1 {
    request
    reply
  }

  api Customer @ 1 {
    operation "createCustomer" {
      method: POST
      path: "/customers"
      request: CustomerRequest @ 1
      responses {
        201: CustomerReply @ 1
        409: ProblemDetails @ 1
      }
    }

    operation "getCustomer" {
      method: GET
      path: "/customers/{id}"
      responses {
        200: CustomerReply @ 1
        404: ProblemDetails @ 1
      }
    }
  }
}
```

The exact token spelling is part of implementation planning, but the semantic
shape is fixed by this design:

- `api <model> @ <version>` is a domain item and must resolve to an entity or
  aggregate model version.
- `operation <string>` is unique within the API declaration.
- `method` is one of `GET`, `POST`, `PUT`, `PATCH`, or `DELETE` in the first
  slice. `HEAD` and `OPTIONS` are reserved until their OpenAPI semantics have
  dedicated tests.
- `path` is an absolute OpenAPI path template beginning with `/`.
- `request` is optional and names exactly one projection version. It is emitted
  as `requestBody` with `application/json`.
- `responses` is required and contains at least one numeric status-code mapping
  to exactly one projection version.
- A response projection reference is written as `<Name> @ <Version>` and is
  resolved in the same domain as the API unless a future cross-domain syntax is
  explicitly accepted.
- `ProblemDetails @ 1` is a conventional projection name for RFC 9457 error
  payloads; the first implementation may require it to be user-authored. A
  built-in standard shape is a follow-up, not an implicit compiler invention.

## 5. Validation rules

Validation occurs during planning/semantic validation, before any OpenAPI
artifact is written. Diagnostics use the existing Modelable source location
and error conventions.

### API and operation identity

1. The bound model/version must exist and be an entity or aggregate.
2. API version must be positive and unique for the same domain/model.
3. Operation names must be unique within an API declaration.
4. The `(path, method)` pair must be unique within an API declaration. The
   OpenAPI path-item object cannot represent two operations with the same
   method and path.
5. Operation names are stable compatibility identities; changing or removing
   one is an API breaking change even if the schemas are unchanged.

### Paths and path parameters

1. Paths must start with `/`, contain no query string or fragment, and use
   OpenAPI `{name}` template syntax.
2. Every template name must match exactly one `@key` field on the API's bound
   model. This deliberately makes key binding explicit through the model
   contract without adding a second parameter declaration language.
3. Every `@key` field used by the operation path must occur exactly once. A
   future slice may support non-key path parameters with explicit typed
   declarations.
4. A path parameter is emitted as an OpenAPI `in: path`, `required: true`
   parameter whose schema is derived from the corresponding model field.
5. The key field name is the template name in Phase B. Renaming a key therefore
   produces a diagnostic and an API compatibility finding rather than silently
   changing a route.

### Projection bindings

1. A request projection must resolve to the API model's `request` auto-kind or
   to a hand-authored projection explicitly accepted by the implementation
   plan. It may not reference a `db` projection.
2. A response projection must resolve to the API model's `reply` auto-kind or
   to a hand-authored projection. It may not reference a `db` projection.
3. Projection versions are resolved exactly; no latest-version inference is
   allowed in an API contract.
4. A body-bearing method may have at most one request body. `GET` and `DELETE`
   may omit a request body; if supplied, it is still emitted as JSON.
5. Response status codes must be valid three-digit HTTP status codes. Duplicate
   status codes within one operation are rejected.

## 6. OpenAPI output

Phase B retains the Phase A document envelope and fills `paths`:

```json
{
  "paths": {
    "/customers/{id}": {
      "get": {
        "operationId": "getCustomer",
        "parameters": [
          {
            "name": "id",
            "in": "path",
            "required": true,
            "schema": {"type": "string", "format": "uuid"}
          }
        ],
        "responses": {
          "200": {
            "description": "Successful response",
            "content": {
              "application/json": {
                "schema": {"$ref": "#/components/schemas/Billing.CustomerReply.v1"}
              }
            }
          }
        },
        "x-modelable": {
          "domain": "Billing",
          "api": "Customer",
          "apiVersion": 1,
          "name": "getCustomer"
        }
      }
    }
  }
}
```

Output rules:

- OpenAPI method keys are lowercase; source method spelling is normalized.
- `operationId` is the source operation name and must be unique across the
  workspace document, not merely within one API declaration.
- Request bodies use `application/json` and a `$ref` to the emitted component
  schema.
- Each response has a deterministic description derived from the status code
  (`Successful response`, `Client error`, etc.) unless a future grammar adds
  explicit descriptions.
- Path parameters are emitted in template order; responses are emitted in
  ascending numeric status-code order.
- `x-modelable` metadata identifies the domain, bound model/API/version, and
  operation name. Standard OpenAPI semantics remain untouched.
- Existing Phase A schema inclusion and component naming rules are unchanged.

## 7. Compatibility and diagnostics

Phase B must add operation-aware compatibility facts without weakening the
existing projection compatibility checks. The minimum facts are:

- operation added: non-breaking;
- operation removed or renamed: breaking;
- method or path changed: breaking;
- request projection changed: evaluated as a request-contract change;
- success/error response removed or its status code changed: breaking;
- additional response status code: non-breaking by default;
- path key renamed or its type changed: breaking.

The compatibility implementation should compare normalized operation IR, not
the serialized OpenAPI JSON. That keeps diagnostics source-oriented and avoids
making JSON key ordering part of compatibility semantics.

## 8. Implementation boundaries

The implementation plan should introduce:

- parser grammar and IR types for API declarations, operations, and responses;
- semantic validation in the existing planner/validation phase;
- an OpenAPI path/operation emitter layered on Phase A's component emitter;
- parser, validation, deterministic-output, and compile-target tests;
- compatibility fixtures for operation add/remove/path/method changes;
- documentation updates for the accepted grammar and generated output.

It must not duplicate schema mapping, projection version resolution, or
artifact writing logic already owned by the compiler and Phase A emitter.

## 9. Acceptance criteria

This design is ready to implement when reviewers agree that:

1. The explicit `api` block is the source of truth for routes.
2. Key-only path parameters are sufficient for the first slice.
3. JSON request bodies and projection-backed responses cover the initial
   consumer need.
4. Error payloads may initially be user-authored `ProblemDetails` projections.
5. Security, non-body parameters, and import hardening remain separate slices.

After acceptance, create a separate implementation plan and keep this design
in the active specs directory until that plan ships; then archive both files
together according to `AGENTS.md`.

## 10. Related roadmap and implementation references

- [`ROADMAP.md`](../../../ROADMAP.md), Priority 5 and Slice F2 — OpenAPI
  sequencing and the requirement for an accepted Phase B grammar design.
- [`docs/compiler-reference.md`](../../compiler-reference.md) — current
  Phase A target behavior and generated-artifact terminology.
- [`docs/language-reference.md`](../../language-reference.md) — existing
  domain, model, projection, and generation grammar conventions.
