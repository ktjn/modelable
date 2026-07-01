from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, str]]


class OpenLineageSyncError(RuntimeError):
    """Raised when an OpenLineage backend rejects or cannot complete a request."""


class OpenLineageClient:
    def __init__(
        self,
        url: str,
        token: str | None = None,
        transport: Transport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = _lineage_api_url(url)
        self.token = token
        self.transport = transport or _urllib_transport
        self.timeout = timeout

    def post_event(self, event: dict[str, object]) -> None:
        body = json.dumps(event, indent=2, ensure_ascii=False).encode("utf-8")
        status, response_text = self.transport(
            "POST",
            self.base_url,
            self._headers(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            ),
            body,
            self.timeout,
        )
        _raise_for_status(status, response_text, "post OpenLineage event")

    def _headers(self, headers: dict[str, str]) -> dict[str, str]:
        if self.token:
            return {**headers, "Authorization": f"Bearer {self.token}"}
        return headers


def _lineage_api_url(url: str) -> str:
    normalized = url.rstrip("/")
    suffix = "/api/v1/lineage"
    if normalized.endswith(suffix):
        return normalized
    return f"{normalized}{suffix}"


def _raise_for_status(status: int, response_text: str, action: str) -> None:
    if 200 <= status < 300:
        return
    detail = response_text.strip()
    suffix = f": {detail}" if detail else ""
    raise OpenLineageSyncError(f"OpenLineage {action} failed with HTTP {status}{suffix}")


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
        raise OpenLineageSyncError(f"OpenLineage request failed: {exc.reason}") from exc
