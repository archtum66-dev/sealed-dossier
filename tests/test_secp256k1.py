"""secp256k1 vector and negative tests."""

import json
from pathlib import Path

import pytest

from sealed.secp256k1 import (
    address_from_private_key,
    eip191_hash,
    personal_sign,
    recover_address,
)

_VECTORS = Path(__file__).resolve().parent / "vectors" / "crypto_vectors.json"


def _load_vectors():
    with _VECTORS.open(encoding="utf-8") as f:
        return json.load(f)


def test_address_from_private_key_vectors():
    for entry in _load_vectors()["address_from_private_key"]:
        priv = int(entry["private_key"], 16)
        assert address_from_private_key(priv) == entry["address"]


def test_personal_sign_vectors():
    for entry in _load_vectors()["personal_sign"]:
        priv = int(entry["private_key"], 16)
        text = entry["text"]
        mh = eip191_hash(text).hex()
        assert mh == entry["message_hash"].removeprefix("0x")
        sig = personal_sign(text, priv)
        assert sig == entry["signature"]
        addr = recover_address(eip191_hash(text), sig)
        assert addr == entry["address"]


def test_recover_v_zero_one_same_as_27_28():
    entry = _load_vectors()["personal_sign"][0]
    text = entry["text"]
    mh = eip191_hash(text)
    sig = entry["signature"]
    body = sig[2:-2]
    assert recover_address(mh, "0x" + body + "00") == entry["address"]
    assert recover_address(mh, "0x" + body + "01") == entry["address"]


def test_flip_signature_bit_breaks_recovery():
    entry = _load_vectors()["personal_sign"][0]
    mh = eip191_hash(entry["text"])
    sig = entry["signature"]
    flipped = "0x" + ("0" if sig[2] == "a" else "a") + sig[3:]
    with pytest.raises(ValueError):
        recover_address(mh, flipped)


def test_flip_text_changes_address():
    entry = _load_vectors()["personal_sign"][0]
    priv = int(entry["private_key"], 16)
    sig = personal_sign(entry["text"] + "x", priv)
    addr = recover_address(eip191_hash(entry["text"]), sig)
    assert addr != entry["address"]


def test_malformed_signature_raises():
    mh = b"\x00" * 32
    with pytest.raises(ValueError):
        recover_address(mh, "0x" + "ab" * 65)
    with pytest.raises(ValueError):
        recover_address(mh, "ab" * 65)
