"""Local HTTP mock of NEAR AI Cloud for offline tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from sealed.secp256k1 import address_from_private_key, personal_sign
from sealed.verify import sha256_text

TEST_API_KEY = "test-key"
_TEST_PRIVATE_KEY = int(
    "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318", 16
)
_TEST_ADDRESS = address_from_private_key(_TEST_PRIVATE_KEY)

# Mutable test hooks (set before starting the server).
tamper_response_hash = False
wrong_signer = False

_MODELS = {
    "object": "list",
    "data": [
        {
            "id": "Qwen/Qwen3.8-27B",
            "owned_by": "nearai",
            "pricing": {"input": 0.5, "output": 1.0},
            "context_length": 131072,
        },
        {
            "id": "anthropic/claude-haiku-4-5",
            "owned_by": "anthropic",
            "pricing": {"input": 1.0, "output": 5.0},
            "context_length": 200000,
        },
    ],
}

_chats: dict[str, dict] = {}


class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _json_response(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {TEST_API_KEY}":
            self._json_response(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/v1/models":
            self._json_response(200, _MODELS)
            return
        if path.startswith("/v1/signature/"):
            if not self._require_auth():
                return
            chat_id = path.split("/")[-1]
            chat = _chats.get(chat_id)
            if chat is None:
                self._json_response(404, {"error": "not found"})
                return
            req_h = sha256_text(chat["request_body"])
            resp_h = sha256_text(chat["response_text"])
            if tamper_response_hash:
                resp_h = "0" * 64
            signed_text = f"{req_h}:{resp_h}"
            signature = personal_sign(signed_text, _TEST_PRIVATE_KEY)
            signer = "0x" + "0" * 40 if wrong_signer else _TEST_ADDRESS
            self._json_response(
                200,
                {
                    "text": signed_text,
                    "signature": signature,
                    "signing_address": signer,
                    "chat_id": chat_id,
                },
            )
            return
        if path == "/v1/attestation/report":
            model = query.get("model", [""])[0]
            nonce = query.get("nonce", [""])[0]
            signing_address = query.get("signing_address", [""])[0]
            self._json_response(
                200,
                {
                    "model": model,
                    "nonce": nonce,
                    "signing_address": signing_address,
                    "signing_algo": "ecdsa",
                },
            )
            return
        self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/v1/chat/completions":
            self._json_response(404, {"error": "not found"})
            return
        if not self._require_auth():
            return
        raw = self._read_body()
        request_body = raw.decode("utf-8")
        try:
            payload = json.loads(request_body)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "bad json"})
            return
        messages = payload.get("messages") or []
        user_bits = []
        for msg in messages:
            if msg.get("role") == "user":
                user_bits.append(msg.get("content", ""))
        content = (
            "Based on [S1], the tenant owes the rent. "
            "Placeholders stay as written."
        )
        chat_id = f"chat-{len(_chats) + 1}"
        response_obj = {
            "id": chat_id,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        response_text = json.dumps(response_obj)
        _chats[chat_id] = {
            "request_body": request_body,
            "response_text": response_text,
            "model": payload.get("model"),
        }
        self._json_response(200, response_obj)


def start_mock_server() -> tuple[ThreadingHTTPServer, str]:
    """Bind 127.0.0.1 port 0 and serve in a daemon thread."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def reset_mock_state() -> None:
    global tamper_response_hash, wrong_signer
    tamper_response_hash = False
    wrong_signer = False
    _chats.clear()
