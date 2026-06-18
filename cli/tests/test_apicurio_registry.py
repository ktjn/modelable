import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.registry.apicurio import ApicurioArtifact, ApicurioRegistryClient


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


def test_apicurio_client_publishes_json_schema_artifact() -> None:
    transport = RecordingTransport([(200, '{"globalId": 10}')])
    client = ApicurioRegistryClient("http://registry.example/apis/registry/v3", token="secret", transport=transport)

    client.publish_json_schema(
        ApicurioArtifact(
            artifact_id="customer.Customer.v1",
            version="1",
            content={"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Customer"},
        ),
        group="contracts",
    )

    method, url, headers, body = transport.requests[0]
    assert method == "POST"
    assert url == "http://registry.example/apis/registry/v3/groups/contracts/artifacts"
    assert headers["Authorization"] == "Bearer secret"
    assert headers["Content-Type"] == "application/json"
    request = json.loads(body.decode("utf-8"))
    assert request["artifactId"] == "customer.Customer.v1"
    assert request["artifactType"] == "JSON"
    assert request["firstVersion"]["version"] == "1"
    assert json.loads(request["firstVersion"]["content"]["content"])["title"] == "Customer"


def test_publish_apicurio_dry_run_lists_json_schema_artifacts(tmp_path: Path) -> None:
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
        ["publish", "apicurio", str(mdl), "--url", "http://registry.example", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert "customer.Customer.v1" in result.output


def test_pull_apicurio_writes_schema_artifact(tmp_path: Path) -> None:
    transport = RecordingTransport(
        [(200, '{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"Customer"}')]
    )
    client = ApicurioRegistryClient("http://registry.example", transport=transport)

    path = client.pull_json_schema("customer.Customer@1", group="default", out_dir=tmp_path)

    assert path == tmp_path / "customer" / "Customer.v1.json"
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "Customer"
    method, url, headers, body = transport.requests[0]
    assert method == "GET"
    assert (
        url
        == "http://registry.example/apis/registry/v3/groups/default/artifacts/customer.Customer.v1/versions/1/content"
    )
    assert headers["Accept"] == "application/json"
    assert body is None
