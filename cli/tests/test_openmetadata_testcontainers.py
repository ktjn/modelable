from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from click.testing import CliRunner
from testcontainers.compose import DockerCompose

from modelable.cli import cli

OPENMETADATA_VERSION = "1.12.11"


@pytest.mark.skipif(
    os.getenv("MODELABLE_OPENMETADATA_TESTCONTAINERS") != "1",
    reason="set MODELABLE_OPENMETADATA_TESTCONTAINERS=1 to run the OpenMetadata Docker Compose smoke test",
)
def test_openmetadata_export_with_testcontainers(tmp_path: Path) -> None:
    compose_dir = tmp_path / "openmetadata-compose"
    compose_dir.mkdir()
    _write_openmetadata_compose(compose_dir / "docker-compose.yml")

    with DockerCompose(compose_dir, compose_file_name="docker-compose.yml", pull=True, wait=True) as compose:
        host, port = compose.get_service_host_and_port("openmetadata-server", 8585)
        base_url = f"http://{host}:{port}"
        _wait_for_openmetadata(base_url)

        source_dir = tmp_path / "models"
        source_dir.mkdir()
        (source_dir / "customer.mdl").write_text(
            """
domain customer {
  owner: "customer-team"
  description: "Customer contracts for catalog smoke testing."

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii
    @classification("confidential")
    email: string
    displayName: string
  }

  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    email <- c.email
    displayName <- c.displayName
  }
}
""",
            encoding="utf-8",
        )
        out_dir = tmp_path / "openmetadata-out"

        result = CliRunner().invoke(
            cli,
            ["compile", str(source_dir), "--target", "openmetadata", "--out", str(out_dir)],
        )

    assert result.exit_code == 0, result.output
    artifact = out_dir / "customer.openmetadata.json"
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["name"] == "customer"
    assert any(asset["fullyQualifiedName"] == "modelable.customer.Customer.v1" for asset in data["assets"])
    assert any(edge["to"] == "modelable.customer.CustomerSummary.v1.email" for edge in data["lineage"])


def _wait_for_openmetadata(base_url: str) -> None:
    deadline = time.monotonic() + 240
    url = f"{base_url}/api/v1/system/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(2)
    raise AssertionError(f"OpenMetadata did not become healthy at {url}: {last_error}")


def _write_openmetadata_compose(path: Path) -> None:
    path.write_text(
        f"""
services:
  mysql:
    image: docker.getcollate.io/openmetadata/db:{OPENMETADATA_VERSION}
    command: "--sort_buffer_size=10M"
    environment:
      MYSQL_ROOT_PASSWORD: password
    healthcheck:
      test: mysql --user=root --password=$$MYSQL_ROOT_PASSWORD --silent --execute "use openmetadata_db"
      interval: 15s
      timeout: 10s
      retries: 10

  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:9.3.0
    environment:
      - discovery.type=single-node
      - ES_JAVA_OPTS=-Xms512m -Xmx512m
      - xpack.security.enabled=false
    healthcheck:
      test: "curl -s http://localhost:9200/_cluster/health?pretty | grep status | grep -qE 'green|yellow' || exit 1"
      interval: 15s
      timeout: 10s
      retries: 10

  execute-migrate-all:
    image: docker.getcollate.io/openmetadata/server:{OPENMETADATA_VERSION}
    command: "./bootstrap/openmetadata-ops.sh migrate"
    environment: &openmetadata-env
      OPENMETADATA_CLUSTER_NAME: openmetadata
      SERVER_PORT: 8585
      SERVER_ADMIN_PORT: 8586
      LOG_LEVEL: INFO
      AUTHENTICATION_PROVIDER: basic
      AUTHORIZER_CLASS_NAME: org.openmetadata.service.security.DefaultAuthorizer
      AUTHORIZER_REQUEST_FILTER: org.openmetadata.service.security.JwtFilter
      AUTHORIZER_ADMIN_PRINCIPALS: "[admin]"
      AUTHORIZER_ALLOWED_REGISTRATION_DOMAIN: '["all"]'
      AUTHORIZER_INGESTION_PRINCIPALS: "[ingestion-bot]"
      AUTHORIZER_PRINCIPAL_DOMAIN: open-metadata.org
      AUTHORIZER_ALLOWED_DOMAINS: "[]"
      AUTHORIZER_ENFORCE_PRINCIPAL_DOMAIN: "false"
      AUTHORIZER_ENABLE_SECURE_SOCKET: "false"
      AUTHENTICATION_PUBLIC_KEYS: "[http://localhost:8585/api/v1/system/config/jwks]"
      AUTHENTICATION_AUTHORITY: https://accounts.google.com
      AUTHENTICATION_ENABLE_SELF_SIGNUP: "true"
      RSA_PUBLIC_KEY_FILE_PATH: ./conf/public_key.der
      RSA_PRIVATE_KEY_FILE_PATH: ./conf/private_key.der
      JWT_ISSUER: open-metadata.org
      JWT_KEY_ID: Gb389a-9f76-gdjs-a92j-0242bk94356
      PIPELINE_SERVICE_CLIENT_ENDPOINT: http://ingestion:8080
      SERVER_HOST_API_URL: http://openmetadata-server:8585/api
      PIPELINE_SERVICE_CLIENT_VERIFY_SSL: no-ssl
      DB_DRIVER_CLASS: com.mysql.cj.jdbc.Driver
      DB_SCHEME: mysql
      DB_PARAMS: allowPublicKeyRetrieval=true&useSSL=false&serverTimezone=UTC
      DB_USE_SSL: "false"
      DB_USER: openmetadata_user
      DB_USER_PASSWORD: openmetadata_password
      DB_HOST: mysql
      DB_PORT: 3306
      OM_DATABASE: openmetadata_db
      ELASTICSEARCH_HOST: elasticsearch
      ELASTICSEARCH_PORT: 9200
      ELASTICSEARCH_SCHEME: http
      SEARCH_TYPE: elasticsearch
      EVENT_MONITOR: prometheus
      SECRET_MANAGER: db
      PIPELINE_SERVICE_CLIENT_CLASS_NAME: org.openmetadata.service.clients.pipeline.airflow.AirflowRESTClient
      PIPELINE_SERVICE_IP_INFO_ENABLED: "false"
      PIPELINE_SERVICE_CLIENT_SECRETS_MANAGER_LOADER: noop
      FERNET_KEY: jJ/9sz0g0OHxsfxOoSfdFdmk3ysNmPRnH3TUAbz3IHA=
      OPENMETADATA_HEAP_OPTS: -Xmx1G -Xms1G
      WEB_CONF_URI_PATH: /api
    depends_on:
      mysql:
        condition: service_healthy
      elasticsearch:
        condition: service_healthy

  openmetadata-server:
    image: docker.getcollate.io/openmetadata/server:{OPENMETADATA_VERSION}
    environment: *openmetadata-env
    ports:
      - "8585"
      - "8586"
    depends_on:
      execute-migrate-all:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8586/healthcheck"]
      interval: 15s
      timeout: 10s
      retries: 10
""",
        encoding="utf-8",
    )
