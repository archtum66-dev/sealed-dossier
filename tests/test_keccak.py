"""Keccak-256 vector tests."""

import json
from pathlib import Path

from sealed.keccak import keccak256

_VECTORS = Path(__file__).resolve().parent / "vectors" / "crypto_vectors.json"


def _load_keccak_vectors():
    with _VECTORS.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["keccak256"]


def test_keccak256_vectors():
    for entry in _load_keccak_vectors():
        raw = bytes.fromhex(entry["input_hex"]) if entry["input_hex"] else b""
        got = keccak256(raw).hex()
        assert got == entry["keccak256"], entry.get("label", entry["input_hex"][:20])
