import json

from click.testing import CliRunner

from modelable.cli import cli


def _build_index(tmp_path):
    source = tmp_path / "docs"
    source.mkdir()
    (source / "guide.md").write_text("# Guide\n\nInstall with uv.", encoding="utf-8")
    output = tmp_path / "index"
    result = CliRunner().invoke(cli, ["docs-index", str(source), "--out", str(output)])
    assert result.exit_code == 0, result.output
    return output / "manifest.json"


def _write_corpus(tmp_path):
    corpus = tmp_path / "evaluation.yaml"
    corpus.write_text(
        "cases:\n  - question: install\n    relevant_chunks:\n      - guide.md#guide\n",
        encoding="utf-8",
    )
    return corpus


def test_docs_eval_reports_human_metrics(tmp_path):
    index = _build_index(tmp_path)
    corpus = _write_corpus(tmp_path)

    result = CliRunner().invoke(cli, ["docs-eval", str(index), str(corpus)])

    assert result.exit_code == 0, result.output
    assert "Cases: 1" in result.output
    assert "Recall@5: 1.0000" in result.output
    assert "MRR: 1.0000" in result.output


def test_docs_eval_json_output_is_machine_readable(tmp_path):
    index = _build_index(tmp_path)
    corpus = _write_corpus(tmp_path)

    result = CliRunner().invoke(cli, ["docs-eval", str(index), str(corpus), "--json"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["case_count"] == 1
    assert report["recall_at_10"] == 1.0


def test_docs_eval_reports_invalid_corpus(tmp_path):
    index = _build_index(tmp_path)
    corpus = tmp_path / "invalid.yaml"
    corpus.write_text("cases: []\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["docs-eval", str(index), str(corpus)])

    assert result.exit_code != 0
    assert "must contain at least one evaluation case" in result.output
