import json

from sealed.nearai import ChatResult
from sealed.receipt import save_receipt, verify_chain, verify_receipt
from sealed.secp256k1 import personal_sign
from sealed.verify import sha256_text, verify_signature

_KEY = int(
    "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318", 16
)
_ADDR = "0x2c7536e3605d9c16a7a3d7b1898e529396a65c23"


def _sample_chat() -> ChatResult:
    req = json.dumps({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    resp = json.dumps({"id": "c1", "choices": [{"message": {"content": "ok"}}]})
    return ChatResult("c1", "m", req, resp, "ok")


def _signature(chat: ChatResult) -> dict:
    signed = f"{sha256_text(chat.request_body)}:{sha256_text(chat.response_text)}"
    return {
        "text": signed,
        "signature": personal_sign(signed, _KEY),
        "signing_address": _ADDR,
        "chat_id": chat.chat_id,
    }


def test_save_and_verify_receipt(tmp_path):
    chat = _sample_chat()
    sig = _signature(chat)
    verification = verify_signature(chat.request_body, chat.response_text, sig)
    root = tmp_path / "receipts"
    path = save_receipt(
        root,
        model="Qwen/Qwen3.8-27B",
        model_tier="confidential",
        chat_result=chat,
        signature_payload=sig,
        verification=verification,
        attestation_report={"signing_address": _ADDR},
        attestation_level="report_lists_signer",
        replaced={"person": 1},
        sources=[{"file": "a.txt", "chunk": 1}],
        answer="ok",
        excerpts="a.txt\t1\ttext\n",
    )
    result = verify_receipt(path)
    assert result["ok"] is True


def test_chain(tmp_path):
    root = tmp_path / "receipts"
    for _ in range(2):
        chat = _sample_chat()
        sig = _signature(chat)
        verification = verify_signature(chat.request_body, chat.response_text, sig)
        save_receipt(
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
            answer="a",
            excerpts="",
        )
    chain = verify_chain(root)
    assert chain["ok"] is True
    assert chain["count"] == 2


def test_tamper_request_fails(tmp_path):
    chat = _sample_chat()
    sig = _signature(chat)
    verification = verify_signature(chat.request_body, chat.response_text, sig)
    root = tmp_path / "receipts"
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
        answer="a",
        excerpts="",
    )
    (path / "request.json").write_text("tampered", encoding="utf-8")
    assert verify_receipt(path)["ok"] is False


def test_receipt_verifies_when_signature_payload_has_no_chat_id(tmp_path):
    chat = _sample_chat()
    sig = _signature(chat)
    del sig["chat_id"]
    verification = verify_signature(chat.request_body, chat.response_text, sig)
    path = save_receipt(
        tmp_path / "receipts",
        model="m",
        model_tier="confidential",
        chat_result=chat,
        signature_payload=sig,
        verification=verification,
        attestation_report=None,
        attestation_level="not_checked",
        replaced={},
        sources=[],
        answer="ok",
        excerpts="",
    )
    assert verify_receipt(path)["ok"] is True


def test_response_with_newlines_survives_save_and_verify(tmp_path):
    req = json.dumps({"model": "m", "messages": []})
    resp = '{"id": "c9",\r\n "choices": [{"message": {"content": "a\\nb"}}]}\n'
    chat = ChatResult("c9", "m", req, resp, "a\nb")
    sig = _signature(chat)
    verification = verify_signature(chat.request_body, chat.response_text, sig)
    assert verification["ok"] is True
    path = save_receipt(
        tmp_path / "receipts",
        model="m",
        model_tier="confidential",
        chat_result=chat,
        signature_payload=sig,
        verification=verification,
        attestation_report=None,
        attestation_level="not_checked",
        replaced={},
        sources=[],
        answer="a\nb",
        excerpts="",
    )
    assert (path / "response.txt").read_bytes() == resp.encode("utf-8")
    assert verify_receipt(path)["ok"] is True
