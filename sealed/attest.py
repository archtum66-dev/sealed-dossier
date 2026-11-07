"""Full attestation check of a NEAR AI Cloud signer.

Offline part (standard library, works on the report stored in every receipt):

- parse the Intel TDX quote (version 4, TDX) and read its report data and measurements;
- report data binds the signing address (first 32 bytes) and the request nonce
  (last 32 bytes), as NEAR AI's official verifier checks it;
- the NVIDIA GPU evidence carries the same request nonce;
- the docker-compose manifest hashes to the quote's ``mr_config_id`` (``01`` + SHA-256),
  and ``mr_td`` matches the TCB info.

Network part (optional, ``--network``):

- the Intel signature chain of the quote, with fresh collateral, through ``dcap-qvl``
  (``pip install dcap-qvl``, the library NEAR AI's verifier uses); without it this check
  is reported as not run;
- NVIDIA's remote attestation service judges the GPU evidence (overall verdict from the
  returned token; like the official verifier, the token's own signature is not checked).

Only when every check passes is the level ``full``. A receipt itself is never changed.
"""

from __future__ import annotations

import base64
import json
import secrets
import urllib.parse
import urllib.request
from hashlib import sha256

NRAS_URL = "https://nras.attestation.nvidia.com/v3/attest/gpu"
DEFAULT_BASE_URL = "https://cloud-api.near.ai"

# TDX quote v4: 48-byte header, then the 584-byte TD report body (TD10).
_HEADER = 48
_BODY = {
    "mr_td": (136, 48),
    "mr_config_id": (184, 48),
    "rtmr0": (328, 48),
    "rtmr1": (376, 48),
    "rtmr2": (424, 48),
    "rtmr3": (472, 48),
    "report_data": (520, 64),
}


def parse_tdx_quote(quote: bytes) -> dict:
    """Fields of a TDX quote v4 that the checks need (no signature check here)."""
    if len(quote) < _HEADER + 584:
        raise ValueError("quote too short for a TDX quote v4")
    version = int.from_bytes(quote[0:2], "little")
    tee_type = int.from_bytes(quote[4:8], "little")
    if version != 4 or tee_type != 0x81:
        raise ValueError(f"not a TDX quote v4 (version {version}, tee type {tee_type:#x})")
    out = {"version": version, "tee_type": tee_type}
    for name, (offset, size) in _BODY.items():
        start = _HEADER + offset
        out[name] = quote[start : start + size].hex()
    return out


def _tcb_info(attestation: dict) -> dict:
    info = attestation.get("info") or {}
    tcb = info.get("tcb_info") if isinstance(info, dict) else None
    if isinstance(tcb, str):
        tcb = json.loads(tcb)
    return tcb if isinstance(tcb, dict) else {}


def offline_checks(attestation: dict, request_nonce: str | None = None) -> dict:
    """Checks that need no network. ``attestation`` is one ``model_attestations`` entry."""
    nonce = (request_nonce or attestation.get("request_nonce") or "").lower()
    signer = str(attestation.get("signing_address", ""))
    checks: dict[str, bool] = {}
    quote = parse_tdx_quote(bytes.fromhex(attestation["intel_quote"]))
    report_data = bytes.fromhex(quote["report_data"])
    try:
        padded = bytes.fromhex(signer.removeprefix("0x")).ljust(32, b"\x00")
    except ValueError:
        padded = b""
    checks["report_data_binds_signer"] = len(padded) == 32 and report_data[:32] == padded
    checks["report_data_embeds_nonce"] = len(nonce) == 64 and report_data[32:64].hex() == nonce
    try:
        gpu_nonce = str(json.loads(attestation["nvidia_payload"]).get("nonce", "")).lower()
    except (KeyError, TypeError, ValueError):
        gpu_nonce = ""
    checks["gpu_evidence_uses_nonce"] = bool(nonce) and gpu_nonce == nonce
    tcb = _tcb_info(attestation)
    compose = tcb.get("app_compose")
    if isinstance(compose, str):
        expected = "01" + sha256(compose.encode()).hexdigest()
        checks["compose_matches_mr_config"] = quote["mr_config_id"].startswith(expected)
    else:
        checks["compose_matches_mr_config"] = False
    if tcb.get("mrtd"):
        checks["mr_td_matches_tcb_info"] = quote["mr_td"] == str(tcb["mrtd"]).lower()
    return {"signer": signer, "nonce": nonce, "checks": checks, "quote": quote}


def intel_check(quote_hex: str) -> dict:
    """Intel signature chain and TCB status through dcap-qvl, if it is installed."""
    try:
        import asyncio

        import dcap_qvl  # type: ignore[import-not-found]
    except ImportError:
        return {"run": False, "ok": False, "detail": "dcap-qvl not installed (pip install dcap-qvl)"}
    try:
        result = asyncio.run(dcap_qvl.get_collateral_and_verify(bytes.fromhex(quote_hex)))
    except Exception as exc:  # noqa: BLE001 - report any verifier failure as a failed check
        return {"run": True, "ok": False, "detail": f"verification failed: {exc}"}
    status = str(getattr(result, "status", ""))
    return {
        "run": True,
        "ok": status in ("UpToDate", "OutOfDate"),
        "detail": f"status {status}, advisories {list(getattr(result, 'advisory_ids', []))}",
    }


def nvidia_check(nvidia_payload: str, timeout: float = 30.0) -> dict:
    """NVIDIA remote attestation of the GPU evidence; overall verdict from the token."""
    req = urllib.request.Request(
        NRAS_URL,
        data=nvidia_payload.encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
        token = body[0][1]
        claims_b64 = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(claims_b64 + "=" * (-len(claims_b64) % 4)))
        verdict = claims.get("x-nvidia-overall-att-result")
    except Exception as exc:  # noqa: BLE001 - any failure means no verdict
        return {"run": True, "ok": False, "detail": f"no verdict: {exc}"}
    return {"run": True, "ok": verdict is True, "detail": f"overall verdict {verdict}"}


def fetch_report(model: str, nonce: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> dict:
    """Fresh attestation report for ``model`` with our own random ``nonce`` (no API key)."""
    url = (
        f"{base_url}/v1/attestation/report?model={urllib.parse.quote(model)}"
        f"&nonce={nonce}&signing_algo=ecdsa"
    )
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def check_attestation(attestation: dict, request_nonce: str | None = None, network: bool = False) -> dict:
    """Offline checks, plus Intel and NVIDIA when ``network`` is true."""
    result = offline_checks(attestation, request_nonce)
    checks = result["checks"]
    details: dict[str, str] = {}
    if network:
        intel = intel_check(attestation["intel_quote"])
        checks["intel_quote_signature_and_tcb"] = intel["ok"]
        details["intel_quote_signature_and_tcb"] = intel["detail"]
        gpu = nvidia_check(attestation["nvidia_payload"])
        checks["nvidia_gpu_verdict"] = gpu["ok"]
        details["nvidia_gpu_verdict"] = gpu["detail"]
    offline_ok = all(v for k, v in checks.items() if k not in ("intel_quote_signature_and_tcb", "nvidia_gpu_verdict"))
    if network and all(checks.values()):
        level = "full"
    elif offline_ok:
        level = "quote_binds_signer"
    else:
        level = "failed"
    return {
        "signer": result["signer"],
        "nonce": result["nonce"],
        "checks": checks,
        "details": details,
        "level": level,
        "mr_config_id": result["quote"]["mr_config_id"],
    }


def new_nonce() -> str:
    return secrets.token_hex(32)
