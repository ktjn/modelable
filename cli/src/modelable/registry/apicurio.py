from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, str]]


class ApicurioRegistryError(RuntimeError):
    """Raised when Apicurio Registry rejects or cannot complete a request."""


@dataclass(frozen=True)
class ApicurioArtifact:
    artifact_id: str
    version: str
    content: dict[str, object]


class ApicurioRegistryClient:
    def __init__(
        self,
        url: str,
        token: str | None = None,
        transport: Transport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = _registry_api_url(url)
        self.token = token
        self.transport = transport or _urllib_transport
        self.timeout = timeout

    def publish_json_schema(self, artifact: ApicurioArtifact, group: str = "default") -> None:
        body = json.dumps(artifact.content, indent=2, ensure_ascii=False).encode("utf-8")
        headers = self._headers(
            {
                "Content-Type": "application/json; artifactType=JSON",
                "Accept": "application/json",
                "X-Registry-ArtifactId": artifact.artifact_id,
                "X-Registry-Version": artifact.version,
            }
        )
        status, response_text = self.transport(
            "POST",
            f"{self.base_url}/groups/{_url_part(group)}/artifacts",
            headers,
            body,
            self.timeout,
        )
        _raise_for_status(status, response_text, f"publish {artifact.artifact_id}")

    def pull_json_schema(self, ref: str, group: str = "default", out_dir: Path = Path(".")) -> Path:
        artifact_id, version = artifact_id_from_ref(ref)
        headers = self._headers({"Accept": "application/json"})
        status, response_text = self.transport(
            "GET",
            (
                f"{self.base_url}/groups/{_url_part(group)}/artifacts/"
                f"{_url_part(artifact_id)}/versions/{_url_part(version)}/content"
            ),
            headers,
            None,
            self.timeout,
        )
        _raise_for_status(status, response_text, f"pull {artifact_id}")

        try:
            content = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ApicurioRegistryError(f"Apicurio returned invalid JSON for {artifact_id}: {exc}") from exc

        if not isinstance(content, dict):
            raise ApicurioRegistryError(f"Apicurio returned non-object JSON for {artifact_id}")

        domain, name = _split_domain_name(artifact_id)
        path = out_dir / domain / f"{name}.v{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def _headers(self, headers: dict[str, str]) -> dict[str, str]:
        if self.token:
            return {**headers, "Authorization": f"Bearer {self.token}"}
        return headers


def artifact_id_from_ref(ref: str) -> tuple[str, str]:
    if "@" not in ref:
        raise ApicurioRegistryError(f"expected ref in form domain.Name@version, got {ref!r}")
    model_ref, version = ref.rsplit("@", 1)
    if not model_ref or not version.isdigit():
        raise ApicurioRegistryError(f"expected ref in form domain.Name@version, got {ref!r}")
    domain, name = _split_model_ref(model_ref)
    return f"{domain}.{name}.v{version}", version


def _registry_api_url(url: str) -> str:
    normalized = url.rstrip("/")
    suffix = "/apis/registry/v3"
    if normalized.endswith(suffix):
        return normalized
    return f"{normalized}{suffix}"


def _split_model_ref(ref: str) -> tuple[str, str]:
    try:
        domain, name = ref.rsplit(".", 1)
    except ValueError as exc:
        raise ApicurioRegistryError(f"expected ref in form domain.Name@version, got {ref!r}") from exc
    if not domain or not name:
        raise ApicurioRegistryError(f"expected ref in form domain.Name@version, got {ref!r}")
    return domain, name


def _split_domain_name(artifact_id: str) -> tuple[str, str]:
    stem = artifact_id.rsplit(".v", 1)[0]
    return _split_model_ref(stem)


def _url_part(value: str) -> str:
    return quote(value, safe="")


def _raise_for_status(status: int, response_text: str, action: str) -> None:
    if 200 <= status < 300:
        return
    detail = response_text.strip()
    suffix = f": {detail}" if detail else ""
    raise ApicurioRegistryError(f"Apicurio {action} failed with HTTP {status}{suffix}")


def _urllib_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, str]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return response.status, payload
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        return exc.code, payload
    except URLError as exc:
        raise ApicurioRegistryError(f"Apicurio request failed: {exc.reason}") from exc
