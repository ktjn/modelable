from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import click

from modelable.commands.common import console
from modelable.rag.evaluation import evaluate_retrieval, load_evaluation_cases
from modelable.rag.retriever import DocumentationRetriever


def register_docs_eval_commands(cli_group: click.Group) -> None:
    cli_group.add_command(docs_eval)


@click.command("docs-eval")
@click.argument(
    "index",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
)
@click.argument(
    "corpus",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--limit",
    type=click.IntRange(min=10),
    default=10,
    show_default=True,
    help="Number of ranked results requested for each question.",
)
@click.option("--json", "as_json", is_flag=True, help="Print a machine-readable JSON report.")
def docs_eval(index: Path, corpus: Path, limit: int, as_json: bool) -> None:
    """Evaluate lexical documentation retrieval for INDEX against CORPUS."""
    try:
        cases = load_evaluation_cases(corpus)
        report = evaluate_retrieval(DocumentationRetriever(index), cases, limit=limit)
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    if as_json:
        click.echo(json.dumps(asdict(report), sort_keys=True))
        return

    console.print(f"Cases: {report.case_count}")
    console.print(f"Recall@5: {report.recall_at_5:.4f}")
    console.print(f"Recall@10: {report.recall_at_10:.4f}")
    console.print(f"MRR: {report.mean_reciprocal_rank:.4f}")
    console.print(f"nDCG@10: {report.ndcg_at_10:.4f}")
    console.print(f"Zero-result rate: {report.zero_result_rate:.4f}")
    console.print(f"Duplicate-source rate: {report.duplicate_source_rate:.4f}")
    for summary in report.category_reports:
        console.print(
            f"Category {summary.category}: {summary.case_count} cases, "
            f"Recall@10 {summary.recall_at_10:.4f}, MRR {summary.mean_reciprocal_rank:.4f}, "
            f"zero-result {summary.zero_result_rate:.4f}"
        )
    if report.failures:
        console.print(f"Failed queries: {len(report.failures)}")
        for failure in report.failures[:10]:
            console.print(f"- [{failure.category}] {failure.question}")
        if len(report.failures) > 10:
            console.print(f"- ... and {len(report.failures) - 10} more")
