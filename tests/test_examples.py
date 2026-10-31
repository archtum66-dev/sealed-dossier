"""The invented sample case in examples/ must pass the same checks as any real dossier."""

import json
from pathlib import Path

from sealed.nearai import NearAI
from sealed.pipeline import ask
from sealed.pseudo import Pseudonymizer, load_entities
from sealed.receipt import verify_chain, verify_receipt
from tests import mock_nearai

ROOT = Path(__file__).resolve().parents[1]
DOSSIER = ROOT / "examples" / "dossier"
ENTITIES = ROOT / "examples" / "entities.json"
QUESTION = "Welche Mängel wurden gemeldet, wann, und wie hat die Vermieterin reagiert?"

# Every string that must never appear in a request: the listed entities and the built-in patterns.
FORBIDDEN = [
    "Beat Zumbrunn", "Zumbrunn", "Corinne", "Wyss", "Marco Gerber", "Alpenblick",
    "Gerber Haustechnik", "Birkenweg", "Hangstrasse", "Musterdorf", "MI.2026.14",
    "756.1234.5678.97", "CH93 0076 2011 6238 5295 7", "079 555 01 23",
    "beat.zumbrunn@example.org", "corinne.wyss@alpenblick-beispiel.example",
]


def test_every_file_of_the_sample_dossier_is_clean_after_pseudonymising():
    pseudo = Pseudonymizer(load_entities(ENTITIES))
    for path in sorted(DOSSIER.glob("*.txt")):
        out = pseudo.apply(path.read_text(encoding="utf-8"))
        assert pseudo.leaks(out) == [], path.name
        for needle in FORBIDDEN:
            assert needle.lower() not in out.lower(), (path.name, needle)


def test_dry_run_request_of_the_sample_case_contains_no_forbidden_string(tmp_path):
    result = ask(
        QUESTION, DOSSIER, ENTITIES, db_path=tmp_path / "i.db", dry_run=True, k=8
    )
    body = json.loads(result["request_body"])
    text = "\n".join(m["content"] for m in body["messages"]).lower()
    for needle in FORBIDDEN:
        assert needle.lower() not in text, needle


def test_sample_case_against_the_mock_gives_a_valid_chain(tmp_path):
    mock_nearai.reset_mock_state()
    server, url = mock_nearai.start_mock_server()
    try:
        api = NearAI(mock_nearai.TEST_API_KEY, base_url=url)
        for _ in range(2):
            result = ask(
                QUESTION, DOSSIER, ENTITIES, api=api,
                db_path=tmp_path / "i.db", receipts_dir=tmp_path / "r",
            )
            assert result["verification"]["ok"] is True
        assert verify_receipt(tmp_path / "r" / "0002")["ok"] is True
        assert verify_chain(tmp_path / "r") == {"ok": True, "count": 2, "problems": []}
        stored = (tmp_path / "r" / "0001" / "request.json").read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            assert needle.lower() not in stored.lower(), needle
    finally:
        server.shutdown()


def test_dry_run_shows_exactly_what_is_sent(tmp_path):
    dry = ask(QUESTION, DOSSIER, ENTITIES, db_path=tmp_path / "i.db", dry_run=True)
    mock_nearai.reset_mock_state()
    server, url = mock_nearai.start_mock_server()
    try:
        api = NearAI(mock_nearai.TEST_API_KEY, base_url=url)
        ask(QUESTION, DOSSIER, ENTITIES, api=api, db_path=tmp_path / "j.db",
            receipts_dir=tmp_path / "r")
        sent = next(iter(mock_nearai._chats.values()))["request_body"]
    finally:
        server.shutdown()
    assert sent == dry["request_body"]


def test_demo_replays_a_stored_run_offline(tmp_path):
    import subprocess, sys
    mock_nearai.reset_mock_state()
    server, url = mock_nearai.start_mock_server()
    try:
        api = NearAI(mock_nearai.TEST_API_KEY, base_url=url)
        for _ in range(2):
            ask(QUESTION, DOSSIER, ENTITIES, api=api, db_path=tmp_path / "i.db",
                receipts_dir=tmp_path / "run")
    finally:
        server.shutdown()
    proc = subprocess.run(
        [sys.executable, "-m", "sealed", "demo", "--fixture", str(tmp_path / "run")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "chain: OK (2 receipts)" in proc.stdout
    assert "signature: OK" in proc.stdout
    assert "Zumbrunn" not in proc.stdout.split("Answer (names restored")[0]
    # a tampered response breaks the replay
    (tmp_path / "run" / "0001" / "response.txt").write_bytes(b"{}")
    bad = subprocess.run(
        [sys.executable, "-m", "sealed", "demo", "--fixture", str(tmp_path / "run")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert bad.returncode == 5
    missing = subprocess.run(
        [sys.executable, "-m", "sealed", "demo", "--fixture", str(tmp_path / "none")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert missing.returncode == 2
