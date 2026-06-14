# Modelable

Modelable is a compiler and language server for versioned, domain-owned data
models. It validates `.mdl` contracts, resolves projections, reports
compatibility and governance findings, traces field-level lineage, and emits
JSON Schema, documentation, and typed-language artifacts.

Modelable is currently a public alpha and requires Python 3.14.

```bash
uv tool install modelable
modelable --version
modelable validate models --strict
modelable compile models --target json-schema --out generated/schema
```

Documentation, examples, release notes, and contribution guidance are
available at <https://github.com/ktjn/modelable>.
