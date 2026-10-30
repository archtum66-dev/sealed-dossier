import json

from sealed.secp256k1 import personal_sign
from sealed.verify import (
    attestation_status,
    parse_signed_text,
    sha256_text,
    verify_signature,
)

_KEY = int(
    "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318", 16
)
_ADDR = "0x2c7536e3605d9c16a7a3d7b1898e529396a65c23"


def test_sha256_text():
    assert len(sha256_text("hello")) == 64


def test_parse_signed_text_two_parts():
    h = "a" * 64
    assert parse_signed_text(f"{h}:{h}") == (h, h)


def test_parse_signed_text_three_parts():
    h = "b" * 64
    assert parse_signed_text(f"model/x:{h}:{h}") == (h, h)


def test_verify_signature_ok():
    req = '{"model":"m","messages":[]}'
    resp = '{"id":"1","choices":[]}'
    req_h = sha256_text(req)
    resp_h = sha256_text(resp)
    signed = f"{req_h}:{resp_h}"
    sig = {
        "text": signed,
        "signature": personal_sign(signed, _KEY),
        "signing_address": _ADDR,
    }
    out = verify_signature(req, resp, sig)
    assert out["ok"] is True
    assert out["signer"].lower() == _ADDR


def test_verify_signature_malformed():
    out = verify_signature("a", "b", {"text": "bad", "signature": "0x00"})
    assert out["ok"] is False
    assert out["signer"] == ""


def test_attestation_status_levels():
    assert attestation_status(None, _ADDR)["level"] == "not_checked"
    report = {"signing_address": _ADDR}
    assert attestation_status(report, _ADDR)["level"] == "report_lists_signer"
    assert attestation_status(report, "0x" + "1" * 40)["level"] == "signer_missing"
