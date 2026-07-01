from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

import pytest
from click.testing import CliRunner
from testcontainers.compose import DockerCompose

from modelable.cli import cli

MARQUEZ_VERSION = "0.51.1"
POSTGRES_VERSION = "14"


@pytest.mark.skipif(
    os.getenv("MODELABLE_OPENLINEAGE_TESTCONTAINERS") != "1",
    reason="set MODELABLE_OPENLINEAGE_TESTCONTAINERS=1 to run the Marquez Docker Compose smoke test",
)
def test_openlineage_sync_round_trips_with_marquez(tmp_path: Path) -> None:
    compose_dir = tmp_path / "marquez-compose"
    compose_dir.mkdir()
    _write_marquez_compose(compose_dir / "docker-compose.yml")
    _write_marquez_db_init(compose_dir / "init-db.sh")

    pull_images = os.getenv("MODELABLE_MARQUEZ_PULL", "1") != "0"
    with DockerCompose(compose_dir, compose_file_name="docker-compose.yml", pull=pull_images, wait=True) as compose:
        api_host, api_port = compose.get_service_host_and_port("marquez", 5000)
        admin_host, admin_port = compose.get_service_host_and_port("marquez", 5001)
        base_url = f"http://{api_host}:{api_port}"
        _wait_for_marquez(f"http://{admin_host}:{admin_port}")

        source_dir = tmp_path / "models"
        source_dir.mkdir()
        (source_dir / "customer.mdl").write_text(
            """
domain customer {
  owner: "customer-team"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
            encoding="utf-8",
        )

        result = CliRunner().invoke(
            cli,
            ["sync", str(source_dir), "--lineage", "marquez", "--url", base_url],
        )
        namespaces = _get_json(f"{base_url}/api/v1/namespaces")
        jobs = _get_json(f"{base_url}/api/v1/namespaces/{quote('modelable://customer', safe='')}/jobs")

    assert result.exit_code == 0, result.output
    assert "synced customer.Customer.v1" in result.output
    assert "synced customer.CustomerSummary.v1" in result.output
    assert "modelable://customer" in json.dumps(namespaces)
    assert "compile/customer.CustomerSummary.v1" in json.dumps(jobs)


def _wait_for_marquez(admin_url: str) -> None:
    deadline = time.monotonic() + 180
    url = f"{admin_url}/healthcheck"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(2)
    raise AssertionError(f"Marquez did not become healthy at {url}: {last_error}")


def _get_json(url: str) -> object:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_marquez_compose(path: Path) -> None:
    path.write_text(
        f"""
services:
  db:
    image: postgres:{POSTGRES_VERSION}
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
      MARQUEZ_USER: marquez
      MARQUEZ_PASSWORD: marquez
      MARQUEZ_DB: marquez
    volumes:
      - ./init-db.sh:/docker-entrypoint-initdb.d/init-db.sh
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 12

  marquez:
    image: marquezproject/marquez:{MARQUEZ_VERSION}
    environment:
      MARQUEZ_PORT: 5000
      MARQUEZ_ADMIN_PORT: 5001
      POSTGRES_HOST: db
      SEARCH_ENABLED: "false"
    ports:
      - "5000"
      - "5001"
    depends_on:
      db:
        condition: service_healthy
""",
        encoding="utf-8",
    )


def _write_marquez_db_init(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" > /dev/null <<-EOSQL
CREATE USER ${MARQUEZ_USER};
ALTER USER ${MARQUEZ_USER} WITH PASSWORD '${MARQUEZ_PASSWORD}';
CREATE DATABASE ${MARQUEZ_DB};
GRANT ALL PRIVILEGES ON DATABASE ${MARQUEZ_DB} TO ${MARQUEZ_USER};
EOSQL
""",
        encoding="utf-8",
        newline="\n",
    )
