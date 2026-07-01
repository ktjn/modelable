import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.registry.openlineage import OpenLineageClient


class RecordingTransport:
    def __init__(self, responses: list[tuple[int, str]] | None = None) -> None:
        self.requests: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.responses = responses or [(200, "{}")]

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> tuple[int, str]:
        self.requests.append((method, url, headers, body))
        return self.responses.pop(0)


def test_openlineage_client_posts_events_to_marquez_lineage_endpoint() -> None:
    transport = RecordingTransport()
    client = OpenLineageClient("http://marquez.example", token="secret", transport=transport)

    client.post_event(
        {
            "eventType": "COMPLETE",
            "eventTime": "1970-01-01T00:00:00.000Z",
            "producer": "https://github.com/ktjn/modelable",
            "run": {"runId": "modelable-customer-Customer-v1"},
            "job": {"namespace": "modelable://customer", "name": "compile/customer.Customer.v1"},
            "inputs": [],
            "outputs": [],
        }
    )

    method, url, headers, body = transport.requests[0]
    assert method == "POST"
    assert url == "http://marquez.example/api/v1/lineage"
    assert headers["Authorization"] == "Bearer secret"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body.decode("utf-8"))["job"]["name"] == "compile/customer.Customer.v1"


def test_sync_lineage_dry_run_lists_openlineage_events(tmp_path: Path) -> None:
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["sync", str(mdl), "--lineage", "marquez", "--url", "http://marquez.example", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert "customer.Customer.v1" in result.output
    assert "http://marquez.example" in result.output
