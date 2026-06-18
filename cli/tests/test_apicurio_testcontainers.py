import json
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from testcontainers.core.container import DockerContainer

from modelable.registry.apicurio import ApicurioArtifact, ApicurioRegistryClient

APICURIO_IMAGE = "apicurio/apicurio-registry:3.3.0"


def test_apicurio_registry_round_trip_with_testcontainers(tmp_path: Path) -> None:
    with DockerContainer(APICURIO_IMAGE).with_exposed_ports(8080) as registry:
        base_url = f"http://{registry.get_container_host_ip()}:{registry.get_exposed_port(8080)}"
        _wait_for_registry(base_url)

        client = ApicurioRegistryClient(base_url, timeout=30.0)
        client.publish_json_schema(
            ApicurioArtifact(
                artifact_id="customer.Customer.v1",
                version="1",
                content={
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "customer.Customer.v1",
                    "type": "object",
                    "title": "Customer",
                    "properties": {"customerId": {"type": "string", "format": "uuid"}},
                    "required": ["customerId"],
                },
            ),
            group="contracts",
        )

        path = client.pull_json_schema("customer.Customer@1", group="contracts", out_dir=tmp_path)

    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["$id"] == "customer.Customer.v1"
    assert schema["properties"]["customerId"]["format"] == "uuid"


def _wait_for_registry(base_url: str) -> None:
    deadline = time.monotonic() + 90
    url = f"{base_url}/apis/registry/v3/system/info"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(1)
    raise AssertionError(f"Apicurio Registry did not become ready at {url}: {last_error}")
