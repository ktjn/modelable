# Modelable Documentation

Start with the [root README](../README.md) for installation and a small working
example. The documents here describe the language and the larger system model.

## User guides

- [Consuming Modelable](consuming-modelable.md): installing the CLI/LSP and VS Code extension, and using generated artifacts.
- [Migration guide](migration-guide.md): bringing existing JSON Schema, OpenAPI, Protobuf, SQL DDL, or Avro definitions into Modelable.
- [Sample scenarios](../samples/README.md): worked `.mdl` examples.
- [Release process](releasing.md): maintainer checklist and repository setup.

## Reference

- [CLI reference](cli-spec.md)
- [IDL language design](idl-design-spec.md)
- [Emitter behavior](emitter-spec.md)
- [Language Server Protocol](lsp-spec.md)
- [CEL expressions](cel-integration-spec.md)
- [Ownership and permissions](ownership-permissions-spec.md)
- [LLM integration](llm-integration-spec.md)

## Architecture and product direction

- [System specification](modelable-system-spec.md): product concepts and source of truth.
- [Adapter architecture](adapter-architecture-spec.md)
- [Distributed lineage](distributed-lineage-spec.md)
- [External-tool boundaries](external-tools-data-modelling.md)
- [Platform usage scenarios](platform-usage-scenarios-spec.md)
- [Technology evaluation](technology-evaluation.md)
- [Data-model language research](data-model-languages.md)

Specifications include future phases where clearly labelled. Current release
scope is summarized in the root README and [ROADMAP.md](../ROADMAP.md).
