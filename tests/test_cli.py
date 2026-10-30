import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests import mock_nearai

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, env: dict | None = None):
    merged = dict(**{k: v for k, v in (env or {}).items() if v is not None})
    return subprocess.run(
        [sys.executable, "-m", "sealed", *args],
        cwd=ROOT,
        env={**dict(**__import__("os").environ), **merged},
        capture_output=True,
        text=True,
    )


def test_ask_dry_run(tmp_path):
    dossier = tmp_path / "d"
    dossier.mkdir()
    (dossier / "a.txt").write_text("Hans Muster Mietzins", encoding="utf-8")
    entities = tmp_path / "e.json"
    entities.write_text(
        json.dumps({"person": ["Hans Muster"], "org": [], "place": [], "case": [], "other": []}),
        encoding="utf-8",
    )
    proc = _run(
        "ask",
        "Mietzins?",
        "--folder",
        str(dossier),
        "--entities",
        str(entities),
        "--db",
        str(tmp_path / "i.db"),
        "--dry-run",
    )
    assert proc.returncode == 0
    assert "Hans Muster" not in proc.stdout
    assert "leak check passed" in proc.stderr


def test_verify_receipt_cli(tmp_path):
    from sealed.nearai import ChatResult
    from sealed.receipt import save_receipt
    from sealed.secp256k1 import personal_sign
    from sealed.verify import sha256_text, verify_signature

    key = int(
        "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318", 16
    )
    addr = "0x2c7536e3605d9c16a7a3d7b1898e529396a65c23"
    req = json.dumps({"model": "m", "messages": []})
    resp = json.dumps({"id": "1", "choices": []})
    chat = ChatResult("1", "m", req, resp, "x")
    signed = f"{sha256_text(req)}:{sha256_text(resp)}"
    sig = {
        "text": signed,
        "signature": personal_sign(signed, key),
        "signing_address": addr,
        "chat_id": "1",
    }
    verification = verify_signature(req, resp, sig)
    root = tmp_path / "r"
    path = save_receipt(
        root,
        model="m",
        model_tier="confidential",
        chat_result=chat,
        signature_payload=sig,
        verification=verification,
        attestation_report=None,
        attestation_level="not_checked",
        replaced={},
        sources=[],
        answer="x",
        excerpts="",
    )
    proc = _run("verify", str(path))
    assert proc.returncode == 0
    assert "signature: OK" in proc.stdout


def test_missing_api_key_exit_2(tmp_path):
    dossier = tmp_path / "d"
    dossier.mkdir()
    (dossier / "a.txt").write_text("text", encoding="utf-8")
    entities = tmp_path / "e.json"
    entities.write_text(
        json.dumps({"person": [], "org": [], "place": [], "case": [], "other": []}),
        encoding="utf-8",
    )
    env = dict(**__import__("os").environ)
    env.pop("NEARAI_API_KEY", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sealed",
            "ask",
            "q",
            "--folder",
            str(dossier),
            "--entities",
            str(entities),
            "--db",
            str(tmp_path / "i.db"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
