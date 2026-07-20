from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import click
from rich.console import Console

from modelable.commands.diff import run_diff
from modelable.compiler.workspace import load_workspace
from modelable.llm.config import resolve_llm_config
from modelable.llm.conversation import ConversationSession
from modelable.llm.engine import (
    answer_model_question_cli,
    attach_external_version,
    describe_path_or_ref,
    explain_validation,
    generate_entity_from_prompt,
    import_definition,
    recommend_cli,
    render_attach_audit_summary,
    render_update_audit_summary,
    render_write_audit_summary,
    suggest_projection,
    transform_ref_to_target,
    update_definition,
    validate_generated_text,
)
from modelable.llm.provenance import (
    AttachmentRecord,
    build_write_provenance,
    write_attachment_record,
    write_provenance_sidecar,
)
from modelable.llm.providers import build_provider

console = Console()


def register_llm_commands(cli_group: click.Group) -> None:
    cli_group.add_command(describe)
    cli_group.add_command(generate)
    cli_group.add_command(import_model)
    cli_group.add_command(diff)
    cli_group.add_command(update)
    cli_group.add_command(attach)
    cli_group.add_command(transform)
    cli_group.add_command(suggest_projection_cmd)
    cli_group.add_command(ask)
    cli_group.add_command(recommend)
    cli_group.add_command(explain)
    cli_group.add_command(chat)


@click.command()
@click.argument("target", required=False)
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=None)
def describe(target: str | None, path: Path | None) -> None:
    """Describe a model, projection, or workspace."""
    if target is None and path is None:
        raise click.UsageError("provide a model ref or --path")
    console.print(describe_path_or_ref(path=path, ref=target))


def _detect_format(path: Path) -> str | None:
    import json

    import yaml

    suffix = path.suffix.lower()
    if suffix in {".yml", ".yaml"}:
        try:
            content = path.read_text(encoding="utf-8")
            doc = yaml.safe_load(content)
            if isinstance(doc, dict) and ("models" in doc or "sources" in doc):
                return "dbt"
            if isinstance(doc, dict) and (
                doc.get("kind") == "DataContract"
                or "schema" in doc
                or "schemas" in doc
                or "dataContractSpecification" in doc
            ):
                return "odcs"
        except Exception:
            pass
        return None
    if suffix == ".json":
        try:
            content = path.read_text(encoding="utf-8")
            doc = json.loads(content)
            if isinstance(doc, dict):
                if doc.get("resourceType") == "StructureDefinition":
                    return "fhir"
                if "nodes" in doc:
                    return "dbt"
                if "title" in doc and "type" in doc:
                    return "json-schema"
                if "openapi" in doc or "swagger" in doc:
                    return "openapi"
                if isinstance(doc.get("type"), str) and "fields" in doc:
                    return "avro"
                if isinstance(doc.get("type"), dict) and doc["type"].get("type") == "record":
                    return "avro"
        except Exception:
            pass
    if suffix == ".avsc":
        try:
            content = path.read_text(encoding="utf-8")
            doc = json.loads(content)
            if isinstance(doc, dict) and isinstance(doc.get("type"), str) and "fields" in doc:
                return "avro"
        except Exception:
            pass
    if suffix == ".proto":
        try:
            content = path.read_text(encoding="utf-8")
            if "message " in content:
                return "protobuf"
        except Exception:
            pass
    if suffix in {".sql", ".ddl"}:
        try:
            content = path.read_text(encoding="utf-8")
            upper = content.upper()
            if "CREATE TABLE" in upper or "CREATE VIEW" in upper:
                return "sql"
        except Exception:
            pass
    return None


@click.command()
@click.option("--from", "source", required=True, help="Natural language or source file path.")
@click.option("--format", "source_format", default=None, help="Source format for import paths.")
@click.option("--domain", "domain_name", default=None, help="Override the output domain.")
@click.option("--name", "model_name", default=None, help="Override the output model name.")
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
def generate(
    source: str, source_format: str | None, domain_name: str | None, model_name: str | None, output: Path | None
) -> None:
    """Generate a draft entity definition."""
    source_path = Path(source)
    source_descriptor = f"path={source_path}"
    try:
        if source_path.exists():
            detected = source_format or _detect_format(source_path)
            if detected is not None:
                text = import_definition(source_path, detected, domain_name=domain_name, source_name=model_name)
                source_format = detected
            else:
                text = source_path.read_text(encoding="utf-8")
        else:
            if source_format is not None:
                text = import_definition(source, source_format, domain_name=domain_name, source_name=model_name)
                source_descriptor = "inline"
            else:
                text = generate_entity_from_prompt(source, domain_name=domain_name, model_name=model_name)
                source_descriptor = "prompt"
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except (UnicodeDecodeError, OSError) as exc:
        raise click.ClickException(f"Could not read source: {exc}") from exc

    _mdl, errors = validate_generated_text(text)
    if errors:
        for error in errors:
            console.print(f"[red]ERROR[/red] {error}")
        raise click.ClickException("generated output failed validation")

    rendered = text if text.endswith("\n") else text + "\n"
    if output is not None:
        output.write_text(rendered, encoding="utf-8")
        write_provenance_sidecar(
            output,
            build_write_provenance(
                command="generate",
                artifact_path=output,
                provider="local",
                model="modelable-local",
                validation_status="passed",
                diagnostics_repaired=0,
                inputs={
                    "source": source_descriptor,
                    "format": source_format or "prompt",
                },
            ),
        )
        console.print(f"[green]OK[/green] wrote {output}")
        console.print(
            render_write_audit_summary(
                provider="local",
                model="modelable-local",
                validation_status="passed",
                files_written=str(output),
                inputs=f"{source_descriptor} format={source_format or 'prompt'}",
                diagnostics_repaired=0,
            )
        )
    else:
        console.print(rendered.rstrip())


@click.command(name="import")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format", "source_format", required=True, help="json-schema, openapi, avro, protobuf, sql, dbt, fhir, odcs"
)
@click.option("--domain", "domain_name", default=None)
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
def import_model(source: Path, source_format: str, domain_name: str | None, output: Path | None) -> None:
    """Import a schema or DDL file into Modelable text."""
    try:
        text = import_definition(source, source_format, domain_name=domain_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except (UnicodeDecodeError, OSError) as exc:
        raise click.ClickException(f"Could not read source: {exc}") from exc
    _mdl, errors = validate_generated_text(text)
    if errors:
        for error in errors:
            console.print(f"[red]ERROR[/red] {error}")
        raise click.ClickException("imported definition failed validation")
    if output is not None:
        output.write_text(text, encoding="utf-8")
        write_provenance_sidecar(
            output,
            build_write_provenance(
                command="import",
                artifact_path=output,
                provider="local",
                model="modelable-local",
                validation_status="passed",
                diagnostics_repaired=0,
                inputs={
                    "path": str(source),
                    "format": source_format,
                    "domain": domain_name or "",
                },
            ),
        )
        console.print(f"[green]OK[/green] wrote {output}")
        console.print(
            render_write_audit_summary(
                provider="local",
                model="modelable-local",
                validation_status="passed",
                files_written=str(output),
                inputs=f"path={source} format={source_format}",
                diagnostics_repaired=0,
            )
        )
    else:
        console.print(text.rstrip())


@click.command()
@click.argument("from_ref")
@click.argument("to_ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
def diff(from_ref: str, to_ref: str, path: Path) -> None:
    """Compare two published model versions."""
    run_diff(from_ref, to_ref, path)


@click.command()
@click.argument("ref")
@click.argument("instruction", nargs=-1)
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
@click.option("--preview", is_flag=True, help="Show the edit diff without writing changes.")
@click.option("--provider", "provider", default=None, help="Provider name, for example ollama or anthropic.")
@click.option("--model", "model", default=None, help="Model identifier.")
@click.option("--base-url", "base_url", default=None, help="Provider base URL.")
def update(
    ref: str,
    instruction: tuple[str, ...],
    path: Path,
    output: Path | None,
    preview: bool,
    provider: str | None,
    model: str | None,
    base_url: str | None,
) -> None:
    """Apply a natural-language update to an existing model version."""
    workspace = load_workspace(path)
    llm_config = resolve_llm_config(
        flag_provider=provider,
        flag_model=model,
        flag_base_url=base_url,
        workspace=workspace.mdl.workspace,
    )
    llm_provider = build_provider(llm_config.provider, model=llm_config.model, base_url=llm_config.base_url)
    try:
        result = update_definition(
            path,
            ref,
            " ".join(instruction),
            output=output,
            write=not preview,
            provider=llm_provider,
            llm_config=llm_config,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if preview:
        from modelable.llm.chat import _render_update_preview

        console.print(_render_update_preview(result))
    else:
        write_provenance_sidecar(
            result.path,
            build_write_provenance(
                command="update",
                artifact_path=result.path,
                provider=result.provider,
                model=result.model,
                validation_status="passed",
                diagnostics_repaired=result.diagnostics_repaired,
                inputs={
                    "ref": result.ref,
                    "source_path": str(result.source_path),
                },
            ),
        )
        console.print(result.content.rstrip())
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")
    if not preview:
        console.print(render_update_audit_summary(result))


@click.command()
@click.argument("ref")
@click.option(
    "--source",
    "source",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="External dbt schema.yml or FHIR StructureDefinition JSON file.",
)
@click.option("--source-format", "source_format", type=click.Choice(["dbt", "fhir", "odcs"]), required=True)
@click.option(
    "--source-name",
    "source_name",
    default=None,
    help="dbt model name or FHIR resource name to match, if the source defines multiple.",
)
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
@click.option("--preview", is_flag=True, help="Show the new version diff without writing changes.")
def attach(
    ref: str,
    source: Path,
    source_format: str,
    source_name: str | None,
    path: Path,
    output: Path | None,
    preview: bool,
) -> None:
    """Attach a model version to an external dbt or FHIR source and record drift as a new version."""
    try:
        result = attach_external_version(
            path, ref, source, source_format, source_name=source_name, output=output, write=not preview
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")

    if not result.attached:
        console.print(
            f"[green]OK[/green] {ref} already matches {result.source_descriptor} "
            f"({result.source_format}); no new version created"
        )
        return

    if preview:
        from modelable.llm.chat import _render_update_preview

        console.print(_render_update_preview(result))
        return

    write_attachment_record(
        result.path,
        AttachmentRecord(
            ref=result.ref,
            source_format=result.source_format,
            source_name=result.source_name,
            source_path=result.source_descriptor,
            source_hash=result.source_hash,
            from_version=result.from_version,
            to_version=result.to_version,
            change_kind=result.change_kind,
            changes=[asdict(change) for change in result.changes],
        ),
    )
    console.print(result.content.rstrip())
    console.print(
        f"[green]OK[/green] attached {ref} to {result.source_descriptor} "
        f"({result.source_format}); new version {result.to_version} ({result.change_kind})"
    )
    console.print(render_attach_audit_summary(result))


@click.command()
@click.argument("ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--to",
    "target",
    type=click.Choice(["json-schema", "markdown", "typescript", "csharp", "java", "python", "rust", "go", "dbt-yaml"]),
    required=True,
)
@click.option("--out", "output", type=click.Path(path_type=Path), default=None)
@click.option("--explain", is_flag=True, help="Show a mapping explanation alongside the emitted artifact.")
def transform(ref: str, path: Path, target: str, output: Path | None, explain: bool) -> None:
    """Transform a model or projection into another artifact format."""
    result = transform_ref_to_target(path, ref, target)
    if output is not None:
        output.write_text(result.content, encoding="utf-8")
        write_provenance_sidecar(
            output,
            build_write_provenance(
                command="transform",
                artifact_path=output,
                provider="local",
                model="modelable-local",
                validation_status="passed",
                diagnostics_repaired=0,
                inputs={
                    "ref": ref,
                    "target": target,
                    "path": str(path),
                },
            ),
        )
        console.print(f"[green]OK[/green] wrote {output}")
        console.print(
            render_write_audit_summary(
                provider="local",
                model="modelable-local",
                validation_status="passed",
                files_written=str(output),
                inputs=f"ref={ref} target={target} path={path}",
                diagnostics_repaired=0,
            )
        )
    if explain and result.explanation is not None:
        console.print(result.explanation)
    console.print(result.content)
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


@click.command(name="suggest-projection")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--source", "source_ref", required=True)
@click.option("--consumer", "consumer_domain", required=True)
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
def suggest_projection_cmd(path: Path, source_ref: str, consumer_domain: str, output: Path | None) -> None:
    """Suggest a projection for a consuming domain."""
    text = suggest_projection(path, source_ref, consumer_domain)
    _mdl, errors = validate_generated_text(text)
    if errors:
        for error in errors:
            console.print(f"[red]ERROR[/red] {error}")
        raise click.ClickException("suggested projection failed validation")
    if output is not None:
        output.write_text(text, encoding="utf-8")
        write_provenance_sidecar(
            output,
            build_write_provenance(
                command="suggest-projection",
                artifact_path=output,
                provider="local",
                model="modelable-local",
                validation_status="passed",
                diagnostics_repaired=0,
                inputs={
                    "path": str(path),
                    "source": source_ref,
                    "consumer": consumer_domain,
                },
            ),
        )
        console.print(f"[green]OK[/green] wrote {output}")
        console.print(
            render_write_audit_summary(
                provider="local",
                model="modelable-local",
                validation_status="passed",
                files_written=str(output),
                inputs=f"path={path} source={source_ref} consumer={consumer_domain}",
                diagnostics_repaired=0,
            )
        )
    else:
        console.print(text.rstrip())


@click.command()
@click.argument("question")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
def ask(question: str, path: Path) -> None:
    """Answer a question about the current model workspace."""
    console.print(answer_model_question_cli(path, question))


@click.command()
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--ref", "ref", default=None)
@click.option("--consumer", "consumer", default=None)
def recommend(path: Path, ref: str | None, consumer: str | None) -> None:
    """Provide a recommendation for a model or projection."""
    console.print(recommend_cli(path, ref=ref, consumer=consumer))


@click.command()
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
def explain(path: Path) -> None:
    """Explain current validation errors."""
    console.print(explain_validation(path))


@click.command()
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--ref", "ref", default=None, help="Optional model or projection ref to focus the chat.")
@click.option("--message", "message", default=None, help="Send a single message and exit.")
@click.option("--provider", "provider", default=None, help="Provider name, for example ollama or anthropic.")
@click.option("--model", "model", default=None, help="Model identifier.")
@click.option("--base-url", "base_url", default=None, help="Provider base URL.")
def chat(
    path: Path, ref: str | None, message: str | None, provider: str | None, model: str | None, base_url: str | None
) -> None:
    """Chat with a model about the current workspace."""
    workspace = load_workspace(path)
    config = resolve_llm_config(
        flag_provider=provider,
        flag_model=model,
        flag_base_url=base_url,
        workspace=workspace.mdl.workspace,
    )
    llm_provider = build_provider(config.provider, model=config.model, base_url=config.base_url)
    session = ConversationSession(
        path=path,
        provider=llm_provider,
        focused_ref=ref,
        repair_attempts=config.repair_attempts,
        provider_name=config.provider,
        model_name=config.model,
        confirmation_surface="cli-chat",
    )

    try:
        if message is not None:
            if message.strip().lower() in {"/exit", "/quit"}:
                console.print("/exit")
            elif message.strip().lower() in {"/help", "/?"}:
                from modelable.llm.chat import chat_help

                console.print(chat_help())
            else:
                console.print(
                    session.turn(message).text,
                    markup=False,
                    highlight=False,
                )
            session.close()
            return

        console.print("Modelable chat. Type /help for commands or /exit to quit.")
        while True:
            try:
                user_message = click.prompt("you", prompt_suffix="> ", default="", show_default=False)
            except EOFError, click.Abort:
                break
            if not user_message.strip():
                continue
            if user_message.strip().lower() in {"/exit", "/quit"}:
                break
            if user_message.strip().lower() in {"/help", "/?"}:
                from modelable.llm.chat import chat_help

                console.print(f"assistant> {chat_help()}")
                continue
            console.print(
                f"assistant> {session.turn(user_message).text}",
                markup=False,
                highlight=False,
            )
    except BaseException as error:
        try:
            session.close()
        except Exception as cleanup_error:
            error.add_note(str(cleanup_error))
        raise
    else:
        session.close()
