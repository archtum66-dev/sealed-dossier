import json
import os

import pytest

from sealed.nearai import NearAI
from sealed.pipeline import (
    LeakError,
    PolicyError,
    VerificationError,
    ask,
)
from sealed.pseudo import Pseudonymizer
from tests import mock_nearai


@pytest.fixture
def dossier(tmp_path):
    root = tmp_path / "dossier"
    root.mkdir()
    (root / "vertrag.txt").write_text(
        "Mieter Hans Muster schuldet Mietzins.\n\nAktenzeichen MI.2026.14.\n",
        encoding="utf-8",
    )
    entities = tmp_path / "entities.json"
    entities.write_text(
        json.dumps(
            {
                "person": ["Hans Muster"],
                "org": ["Beispiel AG"],
                "place": [],
                "case": [],
                "other": [],
            }
        ),
        encoding="utf-8",
    )
    return root, entities


def test_dry_run_no_network(dossier, tmp_path, monkeypatch):
    folder, entities = dossier

    class Boom(NearAI):
        def chat(self, *a, **k):
            raise AssertionError("network")

    monkeypatch.setenv("NEARAI_API_KEY", mock_nearai.TEST_API_KEY)
    out = ask(
        "Was schuldet der Mieter?",
        folder,
        entities,
        db_path=tmp_path / "idx.db",
        api=Boom("x"),
        dry_run=True,
    )
    assert out["dry_run"] is True
    body = out["request_body"]
    assert "Hans Muster" not in body
    assert "MI.2026.14" not in body


def test_leak_refusal(dossier, tmp_path, monkeypatch):
    folder, entities = dossier
    import sealed.pipeline as pl

    class BadPseudo(Pseudonymizer):
        def apply(self, text: str) -> str:
            return text

    monkeypatch.setattr(pl, "Pseudonymizer", BadPseudo)
    with pytest.raises(LeakError):
        ask(
            "Mietzins",
            folder,
            entities,
            db_path=tmp_path / "idx.db",
            dry_run=True,
        )


def test_incognito_refused(dossier, tmp_path, monkeypatch):
    folder, entities = dossier
    monkeypatch.setenv("NEARAI_API_KEY", mock_nearai.TEST_API_KEY)
    mock_nearai.reset_mock_state()
    server, base = mock_nearai.start_mock_server()
    try:
        api = NearAI(mock_nearai.TEST_API_KEY, base_url=base)
        with pytest.raises(PolicyError):
            ask(
                "Frage",
                folder,
                entities,
                model="anthropic/claude-haiku-4-5",
                db_path=tmp_path / "idx.db",
                receipts_dir=tmp_path / "receipts",
                api=api,
            )
    finally:
        server.shutdown()


def test_full_flow_mock(dossier, tmp_path, monkeypatch):
    folder, entities = dossier
    monkeypatch.setenv("NEARAI_API_KEY", mock_nearai.TEST_API_KEY)
    mock_nearai.reset_mock_state()
    server, base = mock_nearai.start_mock_server()
    try:
        api = NearAI(mock_nearai.TEST_API_KEY, base_url=base)
        result = ask(
            "Mietzins",
            folder,
            entities,
            db_path=tmp_path / "idx.db",
            receipts_dir=tmp_path / "receipts",
            api=api,
        )
        assert result["answer"]
        assert os.path.isdir(result["receipt_dir"])
    finally:
        server.shutdown()


def test_tampered_signature_raises(dossier, tmp_path, monkeypatch):
    folder, entities = dossier
    monkeypatch.setenv("NEARAI_API_KEY", mock_nearai.TEST_API_KEY)
    mock_nearai.reset_mock_state()
    mock_nearai.tamper_response_hash = True
    server, base = mock_nearai.start_mock_server()
    try:
        api = NearAI(mock_nearai.TEST_API_KEY, base_url=base)
        with pytest.raises(VerificationError):
            ask(
                "Mietzins",
                folder,
                entities,
                db_path=tmp_path / "idx.db",
                receipts_dir=tmp_path / "receipts",
                api=api,
            )
    finally:
        mock_nearai.reset_mock_state()
        server.shutdown()
