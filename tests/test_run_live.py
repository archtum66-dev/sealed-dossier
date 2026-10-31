import importlib.util
import shutil
from pathlib import Path

import pytest

from sealed.receipt import verify_chain
from tests import mock_nearai

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_home_key_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NEARAI_API_KEY_FILE", str(tmp_path / "no-such-key-file.txt"))


def _load_script():
    spec = importlib.util.spec_from_file_location("run_live", ROOT / "examples" / "run_live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_live_records_a_valid_chain_against_the_mock(tmp_path, monkeypatch):
    mock_nearai.reset_mock_state()
    server, url = mock_nearai.start_mock_server()
    monkeypatch.setenv("NEARAI_API_KEY", mock_nearai.TEST_API_KEY)
    try:
        out = tmp_path / "run1"
        assert _load_script().main(["--out", str(out), "--base-url", url]) == 0
    finally:
        server.shutdown()
    assert verify_chain(out)["count"] == 3


def test_run_live_refuses_to_overwrite_a_run(tmp_path):
    (tmp_path / "run1").mkdir()
    (tmp_path / "run1" / "0001").mkdir()
    assert _load_script().main(["--out", str(tmp_path / "run1")]) == 2


def test_run_live_accepts_a_pasted_key_with_stray_spaces(tmp_path, monkeypatch):
    mock_nearai.reset_mock_state()
    server, url = mock_nearai.start_mock_server()
    monkeypatch.delenv("NEARAI_API_KEY", raising=False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": f'  "{mock_nearai.TEST_API_KEY}"  ')
    try:
        out = tmp_path / "run1"
        assert _load_script().main(["--out", str(out), "--base-url", url]) == 0
    finally:
        server.shutdown()
    assert verify_chain(out)["count"] == 3


def test_run_live_stops_when_no_key_is_given(tmp_path, monkeypatch):
    monkeypatch.delenv("NEARAI_API_KEY", raising=False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "   ")
    assert _load_script().main(["--out", str(tmp_path / "run1")]) == 2


def test_run_live_resume_asks_only_the_missing_question(tmp_path, monkeypatch):
    mock_nearai.reset_mock_state()
    server, url = mock_nearai.start_mock_server()
    monkeypatch.setenv("NEARAI_API_KEY", mock_nearai.TEST_API_KEY)
    try:
        out = tmp_path / "run1"
        script = _load_script()
        assert script.main(["--out", str(out), "--base-url", url]) == 0
        shutil.rmtree(out / "0003")
        assert script.main(["--out", str(out), "--base-url", url]) == 2
        assert script.main(["--out", str(out), "--base-url", url, "--resume"]) == 0
    finally:
        server.shutdown()
    assert verify_chain(out)["count"] == 3
    assert (out / "0003" / "receipt.json").exists()


def test_run_live_reads_the_key_from_a_key_file(tmp_path, monkeypatch, capsys):
    mock_nearai.reset_mock_state()
    server, url = mock_nearai.start_mock_server()
    monkeypatch.delenv("NEARAI_API_KEY", raising=False)
    key_file = tmp_path / "my-key.txt"
    key_file.write_text(f'"{mock_nearai.TEST_API_KEY}"\r\n', encoding="utf-8")
    monkeypatch.setenv("NEARAI_API_KEY_FILE", str(key_file))
    monkeypatch.setattr("builtins.input", lambda _prompt="": pytest.fail("must not prompt"))
    try:
        out = tmp_path / "run1"
        assert _load_script().main(["--out", str(out), "--base-url", url]) == 0
    finally:
        server.shutdown()
    assert mock_nearai.TEST_API_KEY not in capsys.readouterr().out
    assert verify_chain(out)["count"] == 3


def test_run_live_without_key_and_without_input_stops_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("NEARAI_API_KEY", raising=False)

    def _eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert _load_script().main(["--out", str(tmp_path / "run1")]) == 2
