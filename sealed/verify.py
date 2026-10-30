"""Verify NEAR AI response signatures and attestation reports."""

from __future__ import annotations

import hashlib
import re

from sealed.secp256k1 import eip191_hash, recover_address

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_signed_text(text: str) -> tuple[str, str]:
    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise ValueError("invalid signed text format")
    req_h, resp_h = parts[-2], parts[-1]
    if not _HEX64.match(req_h) or not _HEX64.match(resp_h):
        raise ValueError("invalid hash in signed text")
    return req_h, resp_h


def verify_signature(request_body: str, response_text: str, sig: dict) -> dict:
    result = {
        "request_hash_ok": False,
        "response_hash_ok": False,
        "signature_ok": False,
        "signer": "",
        "ok": False,
    }
    try:
        signed_text = sig["text"]
        signature_hex = sig["signature"]
        signing_address = sig["signing_address"]
        req_h, resp_h = parse_signed_text(signed_text)
        result["request_hash_ok"] = req_h == sha256_text(request_body)
        result["response_hash_ok"] = resp_h == sha256_text(response_text)
        recovered = recover_address(eip191_hash(signed_text), signature_hex)
        result["signer"] = recovered
        result["signature_ok"] = recovered.lower() == signing_address.lower()
        result["ok"] = (
            result["request_hash_ok"]
            and result["response_hash_ok"]
            and result["signature_ok"]
        )
    except (KeyError, TypeError, ValueError):
        pass
    return result


def _report_lists_signer(report: dict, signing_address: str) -> bool:
    target = signing_address.lower()

    def has_addr(obj: dict) -> bool:
        addr = obj.get("signing_address")
        return isinstance(addr, str) and addr.lower() == target

    if has_addr(report):
        return True
    attestations = report.get("model_attestations")
    if isinstance(attestations, list):
        for item in attestations:
            if isinstance(item, dict) and has_addr(item):
                return True
    return False


def attestation_status(report: dict | None, signing_address: str) -> dict:
    if report is None:
        return {"level": "not_checked", "detail": "no attestation report fetched"}
    if _report_lists_signer(report, signing_address):
        return {
            "level": "report_lists_signer",
            "detail": "signing address appears in attestation report",
        }
    return {
        "level": "signer_missing",
        "detail": "signing address not listed in attestation report",
    }
