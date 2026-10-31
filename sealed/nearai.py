"""NEAR AI Cloud HTTP client (stdlib only)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://cloud-api.near.ai"
DEFAULT_MODEL = "Qwen/Qwen3.8-27B"

_SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "models_snapshot.json"


@dataclass
class ChatResult:
    chat_id: str
    model: str
    request_body: str
    response_text: str
    content: str


class ApiError(Exception):
    """NEAR AI API failure (message never contains the API key)."""


def _sanitize_body_snippet(body: str) -> str:
    return body[:200]


class NearAI:
    def __init__(
        self,
        api_key: str | None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key or ""
        env_base = os.environ.get("NEARAI_BASE_URL")
        raw = base_url or env_base or DEFAULT_BASE_URL
        self._base_url = raw.rstrip("/")
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        auth: bool = True,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        url = f"{self._base_url}{path}"
        hdrs = {"User-Agent": "sealed-dossier/0.1", **(headers or {})}
        if auth:
            if not self._api_key:
                raise ApiError("missing API key")
            hdrs["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status = resp.getcode()
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        except urllib.error.URLError as exc:
            raise ApiError(f"network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ApiError("request timed out") from exc
        text = raw.decode("utf-8", errors="replace")
        if status >= 400:
            raise ApiError(f"HTTP {status}: {_sanitize_body_snippet(text)}")
        return status, text

    def list_models(self) -> list[dict]:
        _, text = self._request("GET", "/v1/models", auth=False)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiError(f"invalid JSON: {_sanitize_body_snippet(text)}") from exc
        data = payload.get("data")
        if not isinstance(data, list):
            raise ApiError("models response missing data array")
        return data

    def _load_snapshot(self) -> list[dict]:
        try:
            raw = _SNAPSHOT_PATH.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ApiError("models snapshot unavailable") from exc
        data = payload.get("data")
        if not isinstance(data, list):
            raise ApiError("models snapshot invalid")
        return data

    def tier(self, model_id: str, models: list[dict] | None = None) -> str:
        if models is None:
            try:
                models = self.list_models()
            except ApiError:
                models = self._load_snapshot()
        for entry in models:
            if entry.get("id") == model_id:
                owner = entry.get("owned_by", "")
                if owner == "nearai":
                    return "confidential"
                if owner == "attested 3p":
                    return "attested_3p"
                return "incognito"
        return "unknown"

    def chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 2000,
        temperature: float = 0,
    ) -> ChatResult:
        body_obj = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        request_body = json.dumps(body_obj)
        _, response_text = self._request(
            "POST",
            "/v1/chat/completions",
            body=request_body.encode("utf-8"),
            auth=True,
            headers={"Content-Type": "application/json"},
        )
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ApiError(
                f"invalid JSON: {_sanitize_body_snippet(response_text)}"
            ) from exc
        chat_id = payload.get("id")
        choices = payload.get("choices") or []
        content = ""
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
        if not isinstance(chat_id, str):
            raise ApiError("chat response missing id")
        return ChatResult(
            chat_id=chat_id,
            model=model,
            request_body=request_body,
            response_text=response_text,
            content=str(content),
        )

    def signature(self, chat_id: str, model: str) -> dict:
        path = (
            f"/v1/signature/{chat_id}?model={urllib.parse.quote(model)}"
            "&signing_algo=ecdsa"
        )
        _, text = self._request("GET", path, auth=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiError(f"invalid JSON: {_sanitize_body_snippet(text)}") from exc

    def attestation_report(
        self, model: str, nonce: str, signing_address: str
    ) -> dict:
        q_model = urllib.parse.quote(model)
        q_addr = urllib.parse.quote(signing_address)
        path = (
            f"/v1/attestation/report?model={q_model}&nonce={nonce}"
            f"&signing_algo=ecdsa&signing_address={q_addr}"
        )
        _, text = self._request("GET", path, auth=False)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiError(f"invalid JSON: {_sanitize_body_snippet(text)}") from exc
