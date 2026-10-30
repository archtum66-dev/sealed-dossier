# NEAR AI Cloud: the parts this project uses

Sources (read 30 October 2026): the official verifier `github.com/nearai/nearai-cloud-verifier` (files `py/chat_verifier.py`, `py/model_verifier.py`, MIT licence), `docs.near.ai/cloud/quickstart` and `docs.near.ai/cloud/models`, and the public model list `GET https://cloud-api.near.ai/v1/models`.

## Base URL and authentication

- Base URL: `https://cloud-api.near.ai` (override with `--base-url` or `NEARAI_BASE_URL`; tests use a local mock).
- `Authorization: Bearer <key>` on chat and signature requests. `GET /v1/models` needs no key. The key comes from the environment variable `NEARAI_API_KEY`.

## Chat (OpenAI compatible)

`POST /v1/chat/completions`, header `Content-Type: application/json`.

Body (non-streaming): `{"model": "<id>", "messages": [{"role": "system"|"user"|"assistant", "content": "..."}], "stream": false, "max_tokens": <int>, "temperature": 0}`.

Response JSON: `{"id": "<chat id>", "choices": [{"message": {"role": "assistant", "content": "..."}}], "usage": {...}}`. Reasoning models may add `reasoning_content` next to `content`; this project uses only `content`.

**Exactness matters for verification.** The server signs hashes of the request body and of the response body *as bytes*. So the client must send `body_json = json.dumps(body)` (default separators, `ensure_ascii=True`, so the bytes are pure ASCII) and keep the response body decoded as UTF-8 text exactly as received (no re-serialising). Hash = `sha256(text.encode("utf-8")).hexdigest()`.

## Response signature

`GET /v1/signature/{chat_id}?model={model}&signing_algo=ecdsa` with the bearer header.

Response: `{"text": "<signed text>", "signature": "0x<130 hex chars>", "signing_address": "0x<40 hex>", ...}`.

- `text` has 2 or 3 colon-separated parts. With 2 parts: `request_hash:response_hash`. With 3 parts: `<something>:request_hash:response_hash` (take the last two). Both hashes are lowercase hex SHA-256.
- Valid when: request hash equals `sha256(request body)`, response hash equals `sha256(response body)`, and the signature recovers to `signing_address`.
- The signature is an Ethereum personal-message signature (EIP-191, version `0x45`): signed digest = `keccak256(b"\x19Ethereum Signed Message:\n" + str(len(text_bytes)).encode() + text_bytes)` with `text_bytes = text.encode("utf-8")`. Signature bytes: `r (32) || s (32) || v (1)`, with `v` = 27/28 (accept 0/1 too). Recovered address = last 20 bytes of `keccak256(pubkey_x || pubkey_y)`.

## Attestation report

`GET /v1/attestation/report?model={model}&nonce={64 hex chars}&signing_algo=ecdsa&signing_address={address}` (no key needed).

Response: either a single attestation object, or `{"model_attestations": [ {...}, ... ], "gateway_attestation": {...}}`. Each model attestation object has at least `signing_address` and `signing_algo`; it carries the Intel TDX quote, GPU evidence and `report_data` that binds the signing address and the nonce.

Full verification (Intel TDX quote, NVIDIA GPU evidence, compose manifest, Sigstore provenance) is done by the official verifier (`py/model_verifier.py`, needs `dcap-qvl`, `eth-account`, `requests` and network access to Intel and NVIDIA services). **This project does not re-implement it.** It fetches the report, checks cheaply that the signer of the answer is listed in it, stores the report next to the receipt, and says plainly which level was reached (see `docs/SPEC.md`, "Attestation status").

## Privacy tiers (`GET /v1/models`, field `owned_by`)

| `owned_by` | Tier | Meaning |
|---|---|---|
| `nearai` | confidential | runs in a TEE on NEAR AI's GPU fleet |
| `attested 3p` | attested_3p | runs in the provider's TEE, request path encrypted |
| anything else (`openai`, `anthropic`, `google`, ...) | incognito | routed through the TEE gateway, but the model runs outside a TEE |

Prices in the list are US dollars per million tokens. A snapshot is in `fixtures/models_snapshot_2026-10-30.json`.
